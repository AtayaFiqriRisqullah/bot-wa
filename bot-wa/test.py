from otak import proses_pesan

print('Ketik pesan seperti di WhatsApp. Ketik keluar untuk berhenti.')
while True:
    teks = input('Kamu: ')
    if teks == 'keluar':
        break
    print('Bot :', proses_pesan(teks))