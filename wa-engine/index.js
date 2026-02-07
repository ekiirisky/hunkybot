const { default: makeWASocket, useMultiFileAuthState, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const fs = require('fs');
const mime = require('mime-types');
const path = require('path');
const express = require('express');

const app = express();
app.use(express.json());

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

// --- KONFIGURASI ---
const phoneNumber = process.env.WA_PHONE_NUMBER || '628816883610';
const PYTHON_CHAT_URL = process.env.PYTHON_CHAT_URL || 'http://127.0.0.1:5000/chat';
const WA_AUTH_DIR = process.env.WA_AUTH_DIR || 'auth_session';
const WA_PORT = Number(process.env.WA_PORT || 3000);
const PYTHON_TIMEOUT_MS = Number(process.env.PYTHON_TIMEOUT_MS || 25000);

let currentSocket = null;
let isWaConnected = false;

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
        const buffer = await downloadMediaMessage(msgObject, 'buffer', {}, { logger: pino({ level: 'silent' }) });

        let mimetype = type;
        if (msgObject.message?.imageMessage) mimetype = msgObject.message.imageMessage.mimetype;
        if (msgObject.message?.documentMessage) mimetype = msgObject.message.documentMessage.mimetype;
        if (msgObject.message?.videoMessage) mimetype = msgObject.message.videoMessage.mimetype;

        let extension = mime.extension(mimetype);
        if (!extension) extension = 'bin';

        const fileName = `reply_file_${Date.now()}.${extension}`;
        const savePath = path.join(__dirname, '../temp_downloads', fileName);

        fs.writeFileSync(savePath, buffer);
        return { path: savePath, mime: mimetype };
    } catch (err) {
        logger.error({ err }, 'Gagal download media');
        return null;
    }
}

app.get('/health', (_req, res) => {
    return res.status(isWaConnected ? 200 : 503).json({
        status: isWaConnected ? 'ok' : 'degraded',
        wa_connection: isWaConnected ? 'open' : 'closed',
        python_chat_url: PYTHON_CHAT_URL,
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
        logger.error({ err: e }, 'Gagal kirim reminder');
        return res.status(500).send({ error: e.message });
    }
});

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState(WA_AUTH_DIR);

    const sock = makeWASocket({
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        auth: state,
        browser: ['Ubuntu', 'Chrome', '20.0.04'],
    });

    currentSocket = sock;

    if (!sock.authState.creds.registered) {
        setTimeout(async () => {
            try {
                const code = await sock.requestPairingCode(phoneNumber);
                logger.info({ code }, 'CODE LOGIN');
            } catch (err) {
                logger.error({ err }, 'Gagal request pairing code');
            }
        }, 4000);
    }

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        if (update.connection === 'open') {
            isWaConnected = true;
            logger.info('HUNKY SIAP (MODE REPLY & REMINDER AKTIF)');
        }

        if (update.connection === 'close') {
            isWaConnected = false;
            logger.warn('Koneksi WA tertutup, mencoba reconnect ulang');
            connectToWhatsApp().catch((err) => logger.error({ err }, 'Reconnect gagal'));
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

        if (quotedMsg) {
            const quotedText = quotedMsg.conversation || quotedMsg.extendedTextMessage?.text || '';
            if (quotedText) {
                textMessage = `[User Request]: ${textMessage}\n\n[Data Reply/Forward]: "${quotedText}"`;
            }
        }

        const isImage = content.imageMessage;
        const isDocument = content.documentMessage;
        let targetFile = null;

        if (isImage || isDocument) {
            const msgToDownload = { ...msg, message: content };
            targetFile = await downloadAndSave(msgToDownload, isImage?.mimetype || isDocument?.mimetype);
        } else if (quotedMsg && (quotedMsg.imageMessage || quotedMsg.documentMessage)) {
            const qImg = quotedMsg.imageMessage;
            const qDoc = quotedMsg.documentMessage;
            const fakeMsgObject = {
                key: { remoteJid: sender, id: contextInfo?.stanzaId },
                message: quotedMsg,
            };
            targetFile = await downloadAndSave(fakeMsgObject, qImg?.mimetype || qDoc?.mimetype);
        }

        if (!textMessage && !targetFile) return;

        try {
            const response = await axios.post(
                PYTHON_CHAT_URL,
                {
                    sender,
                    message: textMessage || '',
                    file_path: targetFile ? targetFile.path : null,
                    mime_type: targetFile ? targetFile.mime : null,
                    message_id: messageId,
                },
                { timeout: PYTHON_TIMEOUT_MS },
            );

            if (response.data?.reply) {
                await sock.sendMessage(sender, { text: response.data.reply });
            }
        } catch (error) {
            logger.error(
                {
                    err: error,
                    sender,
                    messageId,
                    status: error.response?.status,
                    data: error.response?.data,
                },
                'Gagal forward pesan ke Python API',
            );
        }
    });
}

app.listen(WA_PORT, () => {
    logger.info({ port: WA_PORT }, 'Server WA (Express) siap');
});

connectToWhatsApp().catch((err) => logger.error({ err }, 'Initial connect gagal'));
