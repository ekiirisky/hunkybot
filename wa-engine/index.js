const { default: makeWASocket, useMultiFileAuthState, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const fs = require('fs');
const mime = require('mime-types');
const path = require('path');

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
        
        let mimetype = type; // Default dari parameter
        
        // Coba deteksi mime asli dari pesan
        if (msgObject.message?.imageMessage) mimetype = msgObject.message.imageMessage.mimetype;
        if (msgObject.message?.documentMessage) mimetype = msgObject.message.documentMessage.mimetype;
        if (msgObject.message?.videoMessage) mimetype = msgObject.message.videoMessage.mimetype;

        let extension = mime.extension(mimetype);
        if (!extension) extension = "bin";

        const fileName = `reply_file_${Date.now()}.${extension}`;
        const savePath = path.join(__dirname, '../temp_downloads', fileName);
        
        fs.writeFileSync(savePath, buffer);
        console.log(`✅ Berhasil mengambil file: ${fileName}`);
        
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
        if (update.connection === 'open') console.log('✅ HUNKY SIAP (MODE REPLY AKTIF)!');
        if (update.connection === 'close') connectToWhatsApp();
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        const msg = messages[0];
        if (!msg.message || msg.key.fromMe) return;

        const sender = msg.key.remoteJid;
        const content = unwrapMessage(msg);
        if (!content) return;

        // 1. Ambil Teks Pesan (Caption atau Chat biasa)
        let textMessage = 
            content.conversation || 
            content.extendedTextMessage?.text || 
            content.imageMessage?.caption || 
            content.documentMessage?.caption || "";

        // 2. Deteksi Media di Pesan SEKARANG (Direct Upload)
        const isImage = content.imageMessage;
        const isDocument = content.documentMessage;
        
        // 3. Deteksi Media di Pesan REPLY (Quoted Message)
        // Ini logika untuk mengambil file dari chat yang di-reply
        const contextInfo = content.extendedTextMessage?.contextInfo || content.imageMessage?.contextInfo || content.documentMessage?.contextInfo;
        const quotedMsg = contextInfo?.quotedMessage;
        
        let targetFile = null;

        // SKENARIO A: User kirim file langsung
        if (isImage || isDocument) {
            console.log("📂 Menerima File Langsung...");
            // Kita bungkus ulang supaya fungsi download mau nerima
            let msgToDownload = { ...msg, message: content }; 
            targetFile = await downloadAndSave(msgToDownload, isImage?.mimetype || isDocument?.mimetype);
        }
        
        // SKENARIO B: User ME-REPLY sebuah file
        else if (quotedMsg) {
            const quotedImage = quotedMsg.imageMessage;
            const quotedDoc = quotedMsg.documentMessage;

            if (quotedImage || quotedDoc) {
                console.log("Vi🔄 Mendeteksi REPLY ke sebuah File...");
                
                // Trik: Kita buat objek pesan palsu yang isinya pesan yang di-reply
                // Supaya library Baileys bisa mendownloadnya
                let fakeMsgObject = {
                    key: {
                        remoteJid: sender,
                        id: contextInfo.stanzaId, // ID pesan yang lama
                    },
                    message: quotedMsg
                };

                targetFile = await downloadAndSave(fakeMsgObject, quotedImage?.mimetype || quotedDoc?.mimetype);
            }
        }

        // Kirim ke Python
        // Kalau targetFile ada isinya (baik dari langsung atau reply), kirim path-nya
        if (textMessage || targetFile) {
            try {
                const response = await axios.post('http://127.0.0.1:5000/chat', {
                    sender: sender,
                    message: textMessage || "",
                    file_path: targetFile ? targetFile.path : null, // Kirim path file
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

connectToWhatsApp();