const { default: makeWASocket, useMultiFileAuthState, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const fs = require('fs');
const mime = require('mime-types');
const path = require('path');
const express = require('express'); 
const app = express();              
app.use(express.json());            

// --- KONFIGURASI ---
const phoneNumber = "628816883610"; // GANTI NOMOR KAMU

// Fungsi Helper: Buka bungkusan pesan
function unwrapMessage(msg) {
    if (!msg.message) return null;
    let content = msg.message;
    if (content.ephemeralMessage) content = content.ephemeralMessage.message;
    if (content.viewOnceMessage) content = content.viewOnceMessage.message;
    if (content.viewOnceMessageV2) content = content.viewOnceMessageV2.message;
    if (content.documentWithCaptionMessage) content = content.documentWithCaptionMessage.message;
    return content;
}

// Fungsi Helper: Download Media
async function downloadAndSave(msgObject, type) {
    try {
        const buffer = await downloadMediaMessage(msgObject, 'buffer', {}, { logger: pino({ level: 'silent' }) });
        
        let mimetype = type; 
        
        if (msgObject.message?.imageMessage) mimetype = msgObject.message.imageMessage.mimetype;
        if (msgObject.message?.documentMessage) mimetype = msgObject.message.documentMessage.mimetype;
        if (msgObject.message?.videoMessage) mimetype = msgObject.message.videoMessage.mimetype;

        let extension = mime.extension(mimetype);
        if (!extension) extension = "bin";

        const fileName = `reply_file_${Date.now()}.${extension}`;
        const savePath = path.join(__dirname, '../temp_downloads', fileName);
        
        fs.writeFileSync(savePath, buffer);
        return { path: savePath, mime: mimetype };
    } catch (err) {
        console.error("❌ Gagal download media:", err);
        return null;
    }
}

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_session');

    const sock = makeWASocket({
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        auth: state,
        browser: ["Ubuntu", "Chrome", "20.0.04"]
    });

    // --- SETUP SERVER PUSH (AGAR BISA DIPERINTAH PYTHON) ---
    // Hapus route lama jika ada (biar tidak numpuk saat reconnect)
    app._router?.stack?.pop(); 
    
    app.post('/send-message', async (req, res) => {
        try {
            const { target_id, message } = req.body;
            console.log(`🔔 Menerima perintah reminder untuk: ${target_id}`);
            
            // Kirim pesan WA
            await sock.sendMessage(target_id, { text: message });
            res.send({ status: "sent" });
        } catch (e) {
            console.error("Gagal kirim reminder:", e);
            res.status(500).send({ error: e.message });
        }
    });

    if (!sock.authState.creds.registered) {
        setTimeout(async () => {
            try {
                const code = await sock.requestPairingCode(phoneNumber);
                console.log(`CODE LOGIN: ${code}`);
            } catch {}
        }, 4000);
    }

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', (update) => {
        if (update.connection === 'open') console.log('✅ HUNKY SIAP (MODE REPLY & REMINDER AKTIF)!');
        if (update.connection === 'close') connectToWhatsApp();
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        const msg = messages[0];
        if (!msg.message || msg.key.fromMe) return;

        const sender = msg.key.remoteJid;
        const content = unwrapMessage(msg);
        if (!content) return;

        let textMessage = 
            content.conversation || 
            content.extendedTextMessage?.text || 
            content.imageMessage?.caption || 
            content.documentMessage?.caption || "";

        const contextInfo = content.extendedTextMessage?.contextInfo || content.imageMessage?.contextInfo || content.documentMessage?.contextInfo;
        const quotedMsg = contextInfo?.quotedMessage;
        
        if (quotedMsg) {
            const quotedText = quotedMsg.conversation || quotedMsg.extendedTextMessage?.text || "";
            if (quotedText) {
                textMessage = `[User Request]: ${textMessage}\n\n[Data Reply/Forward]: "${quotedText}"`;
            }
        }

        const isImage = content.imageMessage;
        const isDocument = content.documentMessage;
        let targetFile = null;

        if (isImage || isDocument) {
            let msgToDownload = { ...msg, message: content }; 
            targetFile = await downloadAndSave(msgToDownload, isImage?.mimetype || isDocument?.mimetype);
        }
        else if (quotedMsg && (quotedMsg.imageMessage || quotedMsg.documentMessage)) {
            const qImg = quotedMsg.imageMessage;
            const qDoc = quotedMsg.documentMessage;
            
            let fakeMsgObject = {
                key: { remoteJid: sender, id: contextInfo.stanzaId },
                message: quotedMsg
            };
            targetFile = await downloadAndSave(fakeMsgObject, qImg?.mimetype || qDoc?.mimetype);
        }

        if (textMessage || targetFile) {
            try {
                const response = await axios.post('http://127.0.0.1:5000/chat', {
                    sender: sender,
                    message: textMessage || "",
                    file_path: targetFile ? targetFile.path : null,
                    mime_type: targetFile ? targetFile.mime : null
                });

                if (response.data.reply) {
                    await sock.sendMessage(sender, { text: response.data.reply });
                }
            } catch (error) {
                // Silent error
            }
        }
    });
}

// --- WAJIB: JALANKAN SERVER PORT 3000 ---
app.listen(3000, () => {
    console.log('🚀 Server WA (Express) siap di port 3000');
});

connectToWhatsApp();