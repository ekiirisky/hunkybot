const { default: makeWASocket, useMultiFileAuthState, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const fs = require('fs');
const mime = require('mime-types');
const path = require('path');
const express = require('express');

const app = express();
app.use(express.json());

// Logger kita buat lebih detail
const logger = pino({ 
    level: process.env.LOG_LEVEL || 'info',
    transport: {
        target: 'pino-pretty',
        options: { colorize: true }
    }
});

// --- KONFIGURASI ---
const phoneNumber = process.env.WA_PHONE_NUMBER || '628816883610';
const PYTHON_CHAT_URL = process.env.PYTHON_CHAT_URL || 'http://127.0.0.1:5000/chat';
const WA_AUTH_DIR = process.env.WA_AUTH_DIR || 'auth_session';
const WA_PORT = Number(process.env.WA_PORT || 3000);
const PYTHON_TIMEOUT_MS = Number(process.env.PYTHON_TIMEOUT_MS || 60000); // Naikkan timeout biar aman

let currentSocket = null;
let isWaConnected = false;

// Pastikan folder temp ada
const tempDir = path.join(__dirname, '../temp_downloads');
if (!fs.existsSync(tempDir)){
    fs.mkdirSync(tempDir, { recursive: true });
}

function normalizeJid(jid) {
    return String(jid || '').split(':')[0];
}

function isBotMentioned(content, contextInfo, botJid) {
    // 1. Cek Metadata Mention (Tulisan Biru)
    const mentioned = contextInfo?.mentionedJid || [];
    // Gunakan phoneNumber config sebagai fallback jika socket user ID belum siap
    const targetJid = normalizeJid(botJid || (phoneNumber + '@s.whatsapp.net')); 
    
    if (mentioned.some((jid) => normalizeJid(jid) === targetJid)) return true;

    // 2. Cek Manual di Text/Caption
    const text =
        content?.conversation ||
        content?.extendedTextMessage?.text ||
        content?.imageMessage?.caption ||
        content?.documentMessage?.caption ||
        '';
    
    const lowered = String(text).toLowerCase();
    if (!lowered) return false;

    const botPhone = targetJid.replace('@s.whatsapp.net', '');
    
    // Trigger Kata Kunci: @hunky, @nomorbot, atau kata "bot"
    return lowered.includes('@hunky') || lowered.includes(`@${botPhone}`) || lowered === 'bot';
}

function unwrapMessage(msg) {
    if (!msg.message) return null;
    let content = msg.message;
    if (content.ephemeralMessage) content = content.ephemeralMessage.message;
    if (content.viewOnceMessage) content = content.viewOnceMessage.message;
    if (content.viewOnceMessageV2) content = content.viewOnceMessageV2.message;
    if (content.documentWithCaptionMessage) content = content.documentWithCaptionMessage.message;
    return content;
}

async function downloadAndSave(msgObject, type) {
    try {
        logger.info('📥 Sedang mendownload media...');
        const buffer = await downloadMediaMessage(msgObject, 'buffer', {}, { logger: pino({ level: 'silent' }) });

        let mimetype = type;
        // Pastikan mimetype diambil dari object yang benar
        const msg = unwrapMessage(msgObject);
        if (msg?.imageMessage) mimetype = msg.imageMessage.mimetype;
        if (msg?.documentMessage) mimetype = msg.documentMessage.mimetype;
        if (msg?.videoMessage) mimetype = msg.videoMessage.mimetype;

        let extension = mime.extension(mimetype);
        if (!extension) extension = 'bin';

        const fileName = `file_${Date.now()}.${extension}`;
        const savePath = path.join(tempDir, fileName);

        fs.writeFileSync(savePath, buffer);
        logger.info({ path: savePath }, '✅ Media tersimpan di VPS');
        return { path: savePath, mime: mimetype };
    } catch (err) {
        logger.error({ err }, '❌ Gagal download media');
        return null;
    }
}

app.get('/health', (_req, res) => {
    return res.status(isWaConnected ? 200 : 503).json({
        status: isWaConnected ? 'ok' : 'degraded',
        wa_connection: isWaConnected ? 'open' : 'closed',
    });
});

app.post('/send-message', async (req, res) => {
    try {
        const { target_id: targetId, message } = req.body || {};
        if (!targetId || !message) {
            return res.status(400).send({ error: 'target_id dan message wajib diisi' });
        }
        if (!currentSocket || !isWaConnected) {
            return res.status(503).send({ error: 'WA socket belum siap' });
        }
        await currentSocket.sendMessage(targetId, { text: message });
        return res.send({ status: 'sent' });
    } catch (e) {
        logger.error({ err: e }, 'Gagal kirim pesan');
        return res.status(500).send({ error: e.message });
    }
});

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState(WA_AUTH_DIR);

    const sock = makeWASocket({
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        auth: state,
        browser: ['HunkyBot', 'Chrome', '1.0.0'],
        markOnlineOnConnect: true
    });

    currentSocket = sock;

    if (!sock.authState.creds.registered) {
        setTimeout(async () => {
            try {
                const code = await sock.requestPairingCode(phoneNumber);
                console.log(`\n\n⚠️  KODE PAIRING: ${code}  ⚠️\n\n`);
            } catch (err) {
                logger.error({ err }, 'Gagal request pairing code');
            }
        }, 4000);
    }

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect } = update;
        if (connection === 'open') {
            isWaConnected = true;
            logger.info('🟢 HUNKY SIAP (Koneksi Stabil)');
        }
        if (connection === 'close') {
            isWaConnected = false;
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== 401;
            logger.warn('🔴 Koneksi WA putus, reconnecting...');
            if(shouldReconnect) connectToWhatsApp();
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        const msg = messages[0];
        if (!msg?.message || msg.key?.fromMe) return;

        const sender = msg.key.remoteJid;
        const messageId = msg.key.id || `${Date.now()}`;
        const content = unwrapMessage(msg);
        if (!content) return;

        // Ekstrak Text (Caption atau Pesan Biasa)
        let textMessage =
            content.conversation ||
            content.extendedTextMessage?.text ||
            content.imageMessage?.caption ||
            content.documentMessage?.caption ||
            '';

        const contextInfo =
            content.extendedTextMessage?.contextInfo ||
            content.imageMessage?.contextInfo ||
            content.documentMessage?.contextInfo;

        const quotedMsg = contextInfo?.quotedMessage;
        
        // FIX: Gunakan user ID dari socket atau fallback ke config phoneNumber
        const myJid = sock.user?.id || (phoneNumber + '@s.whatsapp.net');
        const botHit = isBotMentioned(content, contextInfo, myJid);

        // Logic Quoted (Reply)
        if (quotedMsg) {
            const quotedText = quotedMsg.conversation || quotedMsg.extendedTextMessage?.text || '';
            if (quotedText) {
                textMessage = `[User Request]: ${textMessage}\n\n[Data Reply/Forward]: "${quotedText}"`;
            }
        }

        const isImage = content.imageMessage;
        const isDocument = content.documentMessage;
        let targetFile = null;
        let fileSource = null;

        // Logic Download File
        if (isImage || isDocument) {
            // Kita download file-nya dulu biar siap dikirim ke Python
            const msgToDownload = { ...msg, message: content };
            targetFile = await downloadAndSave(msgToDownload, isImage?.mimetype || isDocument?.mimetype);
            fileSource = targetFile ? 'direct' : null;
        } else if (quotedMsg && (quotedMsg.imageMessage || quotedMsg.documentMessage)) {
            // Handle jika user reply gambar dengan perintah "simpan"
            const qImg = quotedMsg.imageMessage;
            const qDoc = quotedMsg.documentMessage;
            // Hack: Bikin fake message object buat didownload baileys
            const fakeMsgObject = {
                key: { remoteJid: sender, id: contextInfo?.stanzaId },
                message: quotedMsg,
            };
            targetFile = await downloadAndSave(fakeMsgObject, qImg?.mimetype || qDoc?.mimetype);
            fileSource = targetFile ? 'quoted' : null;
        }

        if (!textMessage && !targetFile) return;

        // DEBUG: Lihat apa yang mau dikirim ke Python
        logger.info({ 
            msg: "🚀 MENGIRIM KE PYTHON...", 
            text: textMessage, 
            hasFile: !!targetFile, 
            botHit: botHit 
        });

        try {
            const response = await axios.post(
                PYTHON_CHAT_URL,
                {
                    sender,
                    message: textMessage || '',
                    file_path: targetFile ? targetFile.path : null,
                    mime_type: targetFile ? targetFile.mime : null,
                    file_source: fileSource,
                    bot_hit: botHit, // Ini kunci agar Python memproses di grup
                    message_id: messageId,
                },
                { timeout: PYTHON_TIMEOUT_MS },
            );

            // Jika Python membalas ada reply, kirim ke WA
            if (response.data?.reply) {
                await sock.sendMessage(sender, { text: response.data.reply });
                logger.info("✅ Balasan terkirim ke WA");
            } else if (response.data?.status === 'ignored_file') {
                logger.warn("⚠️ Python mengabaikan file (Trigger/Keyword tidak cocok)");
            }

        } catch (error) {
            logger.error(
                {
                    err: error.message,
                    data: error.response?.data
                },
                '❌ Gagal komunikasi dengan Python API'
            );
        }
    });
}

app.listen(WA_PORT, () => {
    logger.info(`Server WA berjalan di port ${WA_PORT}`);
});

connectToWhatsApp().catch((err) => logger.error({ err }, 'Fatal Error Connect'));
