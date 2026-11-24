const fs = require('fs');
const path = require('path');
const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    downloadMediaMessage
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const pino = require('pino');

// Baca .env dari folder proyek induk (atau folder saat ini) tanpa perlu dependensi tambahan
function muatEnvLokal() {
    const kandidat = [
        path.resolve(__dirname, '..', '.env'),
        path.resolve(__dirname, '.env')
    ];
    for (const fileEnv of kandidat) {
        if (!fs.existsSync(fileEnv)) continue;
        const isi = fs.readFileSync(fileEnv, 'utf8');
        for (const barisMentah of isi.split(/\r?\n/)) {
            const baris = barisMentah.trim();
            if (!baris || baris.startsWith('#')) continue;
            const eq = baris.indexOf('=');
            if (eq === -1) continue;
            const kunci = baris.slice(0, eq).trim();
            let nilai = baris.slice(eq + 1).trim();
            if ((nilai.startsWith('"') && nilai.endsWith('"')) ||
                (nilai.startsWith("'") && nilai.endsWith("'"))) {
                nilai = nilai.slice(1, -1);
            }
            if (!(kunci in process.env)) {
                process.env[kunci] = nilai;
            }
        }
    }
}

muatEnvLokal();

const API_URL = (process.env.API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const INTERVAL_PENGINGAT_MS = Math.max(15, parseInt(process.env.INTERVAL_PENGINGAT_DETIK || '60', 10) || 60) * 1000;
const MODE_TERBUKA = ['1', 'true', 'yes', 'on'].includes((process.env.MODE_TERBUKA || '').trim().toLowerCase());
const MAKS_MEDIA_BYTE = 10 * 1024 * 1024; // 10 MB

function normalisasiNomor(teks) {
    if (!teks) return '';
    const sebelumAt = teks.split('@')[0].split(':')[0];
    let digit = sebelumAt.replace(/\D/g, '');
    if (digit.startsWith('0')) {
        digit = '62' + digit.slice(1);
    }
    return digit;
}

function muatWhitelist() {
    const nomorSet = new Set();
    const jidLangsungSet = new Set();
    const grupSet = new Set();
    let nomorUtama = '';

    const rawNomor = (process.env.NOMOR_KAMU || '').split(',').map((s) => s.trim()).filter(Boolean);
    for (const entri of rawNomor) {
        if (entri.endsWith('@g.us')) {
            grupSet.add(entri);
        } else if (entri.endsWith('@lid')) {
            jidLangsungSet.add(entri);
        } else {
            const norm = normalisasiNomor(entri);
            if (norm) {
                nomorSet.add(norm);
                if (!nomorUtama) nomorUtama = norm;
            }
        }
    }

    const rawGrup = (process.env.WHITELIST_GRUP || '').split(',').map((s) => s.trim()).filter(Boolean);
    for (const g of rawGrup) {
        grupSet.add(g.includes('@') ? g : `${g}@g.us`);
    }

    return { nomorSet, jidLangsungSet, grupSet, nomorUtama };
}

const WHITELIST = muatWhitelist();
let jidTujuanPengingat = WHITELIST.nomorUtama ? `${WHITELIST.nomorUtama}@s.whatsapp.net` : '';
let timerPengingat = null;
let timerAwalPengingat = null;
let sedangCekPengingat = false;

function apakahDiizinkan(msg) {
    const remoteJid = msg.key?.remoteJid || '';
    if (!remoteJid || remoteJid === 'status@broadcast') return false;

    const adaWhitelist = WHITELIST.nomorSet.size > 0 || WHITELIST.jidLangsungSet.size > 0 || WHITELIST.grupSet.size > 0;
    if (!adaWhitelist) {
        if (MODE_TERBUKA) return true;
        console.warn('[Keamanan] NOMOR_KAMU belum diatur di .env. Pesan diabaikan demi keamanan.');
        return false;
    }

    // Pesan grup: harus masuk WHITELIST_GRUP
    if (remoteJid.endsWith('@g.us')) {
        if (!WHITELIST.grupSet.has(remoteJid)) return false;
        if (WHITELIST.nomorSet.size === 0 && WHITELIST.jidLangsungSet.size === 0) return true;
        const kandidatPengirim = [msg.key.participant, msg.key.participantAlt].filter(Boolean);
        return kandidatPengirim.some((jid) =>
            WHITELIST.jidLangsungSet.has(jid) || WHITELIST.nomorSet.has(normalisasiNomor(jid))
        );
    }

    // Pesan pribadi (mendukung JID @s.whatsapp.net maupun @lid Baileys v7 via remoteJidAlt)
    const kandidat = [remoteJid, msg.key.remoteJidAlt].filter(Boolean);
    return kandidat.some((jid) =>
        WHITELIST.jidLangsungSet.has(jid) || WHITELIST.nomorSet.has(normalisasiNomor(jid))
    );
}

function bukaIsiPesan(message) {
    let isi = message;
    for (let i = 0; i < 4 && isi; i++) {
        if (isi.ephemeralMessage?.message) {
            isi = isi.ephemeralMessage.message;
        } else if (isi.viewOnceMessage?.message) {
            isi = isi.viewOnceMessage.message;
        } else if (isi.viewOnceMessageV2?.message) {
            isi = isi.viewOnceMessageV2.message;
        } else if (isi.viewOnceMessageV2Extension?.message) {
            isi = isi.viewOnceMessageV2Extension.message;
        } else if (isi.documentWithCaptionMessage?.message) {
            isi = isi.documentWithCaptionMessage.message;
        } else {
            break;
        }
    }
    return isi;
}

async function fetchDenganTimeout(url, opsi = {}, timeoutMs = 30000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { ...opsi, signal: controller.signal });
    } finally {
        clearTimeout(timer);
    }
}

async function kirimBalasan(sock, tujuan, data) {
    if (!data) return;
    if (data.gambar_base64) {
        const buffer = Buffer.from(data.gambar_base64, 'base64');
        await sock.sendMessage(tujuan, {
            image: buffer,
            caption: data.caption || data.balasan || ''
        });
        return;
    }
    if (data.balasan) {
        await sock.sendMessage(tujuan, { text: data.balasan });
    }
}

function hentikanPenjadwalPengingat() {
    if (timerAwalPengingat) {
        clearTimeout(timerAwalPengingat);
        timerAwalPengingat = null;
    }
    if (timerPengingat) {
        clearInterval(timerPengingat);
        timerPengingat = null;
    }
}

function mulaiPenjadwalPengingat(sock) {
    hentikanPenjadwalPengingat();
    if (!jidTujuanPengingat) {
        console.warn('⚠️ Pengingat proaktif nonaktif karena NOMOR_KAMU belum diisi di .env.');
        return;
    }

    const periksa = async () => {
        if (sedangCekPengingat || !jidTujuanPengingat) return;
        sedangCekPengingat = true;
        try {
            const response = await fetchDenganTimeout(`${API_URL}/pengingat`, {}, 25000);
            if (!response.ok) return;
            const data = await response.json();
            if (data.pesan) {
                console.log(`[Pengingat Proaktif -> ${jidTujuanPengingat}] Mengirim pengingat...`);
                await sock.sendMessage(jidTujuanPengingat, { text: data.pesan });
            }
        } catch (error) {
            console.error('[Pengingat] Gagal memeriksa pengingat:', error.message);
        } finally {
            sedangCekPengingat = false;
        }
    };

    console.log(`⏰ Penjadwal pengingat aktif tiap ${INTERVAL_PENGINGAT_MS / 1000} detik -> ${jidTujuanPengingat}`);
    timerAwalPengingat = setTimeout(periksa, 5000);
    timerPengingat = setInterval(periksa, INTERVAL_PENGINGAT_MS);
}

async function connectToWhatsApp() {
    if (!WHITELIST.nomorSet.size && !WHITELIST.jidLangsungSet.size && !WHITELIST.grupSet.size) {
        console.warn('⚠️ PERINGATAN: NOMOR_KAMU belum diatur di .env. Bot tidak akan membalas nomor mana pun sampai NOMOR_KAMU diisi.');
    } else {
        console.log(`🔒 Whitelist aktif (${WHITELIST.nomorSet.size} nomor, ${WHITELIST.grupSet.size} grup).`);
    }

    const { state, saveCreds } = await useMultiFileAuthState('auth_info');
    const silentLogger = pino({ level: 'silent' });

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        logger: silentLogger
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('\n--- SCAN QR CODE INI DENGAN WHATSAPP NOMOR KEDUA ---');
            qrcode.generate(qr, { small: true });
        }

        if (connection === 'close') {
            hentikanPenjadwalPengingat();
            const shouldReconnect = (lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut);
            console.log('Koneksi terputus. Mencoba menghubungkan kembali...');
            if (shouldReconnect) connectToWhatsApp();
        } else if (connection === 'open') {
            console.log('✅ Bot WhatsApp Baileys berhasil terhubung!');
            mulaiPenjadwalPengingat(sock);
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const msg of messages) {
            if (msg.key.fromMe) continue;

            const from = msg.key.remoteJid;
            if (!apakahDiizinkan(msg)) {
                console.log(`[Abaikan] Pesan dari pengirim tidak terdaftar: ${from}`);
                continue;
            }

            // Simpan JID pribadi yang valid sebagai tujuan pengingat proaktif
            if (!from.endsWith('@g.us') && (!jidTujuanPengingat || from.endsWith('@s.whatsapp.net'))) {
                jidTujuanPengingat = from;
            }

            const isiPesan = bukaIsiPesan(msg.message);
            if (!isiPesan) continue;

            // 1. Foto (Scan Struk Belanja)
            if (isiPesan.imageMessage) {
                const caption = isiPesan.imageMessage.caption || '';
                const mimeType = isiPesan.imageMessage.mimetype || 'image/jpeg';
                console.log(`[Foto Masuk dari ${from}]: caption="${caption}"`);
                try {
                    await sock.sendPresenceUpdate('composing', from);
                    const buffer = await downloadMediaMessage(
                        { ...msg, message: isiPesan },
                        'buffer',
                        {},
                        { logger: silentLogger, reuploadRequest: sock.updateMediaMessage }
                    );
                    if (buffer.length > MAKS_MEDIA_BYTE) {
                        await sock.sendMessage(from, { text: '⚠️ Ukuran foto terlalu besar (maksimal 10 MB).' });
                        continue;
                    }
                    const response = await fetchDenganTimeout(`${API_URL}/proses_media`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            jenis: 'gambar',
                            mime_type: mimeType,
                            data_base64: buffer.toString('base64'),
                            caption,
                            pengirim: from
                        })
                    }, 60000);
                    const data = await response.json();
                    await kirimBalasan(sock, from, data);
                } catch (error) {
                    console.error('Gagal memproses foto:', error.message);
                    await sock.sendMessage(from, { text: '⚠️ Gagal memproses foto struk. Coba kirim ulang.' });
                }
                continue;
            }

            // 2. Voice Note / Audio
            if (isiPesan.audioMessage) {
                const mimeType = isiPesan.audioMessage.mimetype || 'audio/ogg; codecs=opus';
                console.log(`[Voice Note Masuk dari ${from}]: ${mimeType}`);
                try {
                    await sock.sendPresenceUpdate('composing', from);
                    const buffer = await downloadMediaMessage(
                        { ...msg, message: isiPesan },
                        'buffer',
                        {},
                        { logger: silentLogger, reuploadRequest: sock.updateMediaMessage }
                    );
                    if (buffer.length > MAKS_MEDIA_BYTE) {
                        await sock.sendMessage(from, { text: '⚠️ Ukuran voice note terlalu besar (maksimal 10 MB).' });
                        continue;
                    }
                    const response = await fetchDenganTimeout(`${API_URL}/proses_media`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            jenis: 'audio',
                            mime_type: mimeType,
                            data_base64: buffer.toString('base64'),
                            caption: '',
                            pengirim: from
                        })
                    }, 60000);
                    const data = await response.json();
                    await kirimBalasan(sock, from, data);
                } catch (error) {
                    console.error('Gagal memproses voice note:', error.message);
                    await sock.sendMessage(from, { text: '⚠️ Gagal memproses voice note. Coba kirim ulang.' });
                }
                continue;
            }

            // 3. Pesan Teks
            const text = isiPesan.conversation || isiPesan.extendedTextMessage?.text || '';
            if (!text) continue;
            console.log(`[Pesan Masuk dari ${from}]: ${text}`);

            try {
                const response = await fetchDenganTimeout(`${API_URL}/proses`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ teks: text, pengirim: from })
                }, 45000);

                const data = await response.json();
                await kirimBalasan(sock, from, data);
            } catch (error) {
                console.error('Gagal menghubungi API Python:', error.message);
            }
        }
    });
}

connectToWhatsApp();