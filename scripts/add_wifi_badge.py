with open('app/templates/cash.html', 'rb') as f:
    content = f.read()

content = content.replace(b'\r\r\n', b'\n').replace(b'\r\n', b'\n')

badge = b'''      <div id="wifiBadge" onclick="copyWifiUrl()" class="hidden sm:flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-amber-300 border border-slate-700 hover:border-amber-500/50 text-xs font-bold transition shadow cursor-pointer select-none" title="Conectar celulares/tablets en la misma red Wi-Fi">
        <span>\xf0\x9f\x93\xb1</span>
        <span id="wifiIpDisplay" class="font-mono text-[11px]">Wi-Fi</span>
      </div>\n'''

target = b'<div class="flex items-center space-x-2 flex-shrink-0">\n      <a id="navGerenciaTab"'
replacement = b'<div class="flex items-center space-x-2 flex-shrink-0">\n' + badge + b'      <a id="navGerenciaTab"'

content = content.replace(target, replacement, 1)

with open('app/templates/cash.html', 'wb') as f:
    f.write(content)
print('cash.html normalized and updated')
