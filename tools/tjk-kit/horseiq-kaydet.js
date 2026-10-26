/* HorseIQ – TJK sayfa kaydedici (yer imi butonu).
 *
 * Kullanıcının kendi tarayıcısında, kendi açtığı TJK sayfasında, kendi tıklamasıyla çalışır.
 * Sunucuya hiçbir istek atmaz; yalnızca ekranda görünen tabloyu okuyup dosya olarak indirir.
 *
 *  - At sayfası  (…/AtKosuBilgileri?…QueryParameter_AtId=NNN)
 *        -> tjk-at-<AtId>-<isim>.json  (at bilgileri + koşu geçmişi tablosu, ham hücre metinleriyle)
 *  - Günlük Yarış Sonuçları / Programı sayfası
 *        -> ekranda bir liste açar: her koşunun atları ve at sayfalarının bağlantıları
 *           (bağlantıları sen açarsın; her at sayfasında butona bir kez basarsın)
 *
 * Yorumlama (tarih, pist, derece …) Python tarafında yapılır (backend/horseiq/collectors/tjk/horse_history.py),
 * böylece TJK sayfa düzeni değişirse yalnızca Python tarafı güncellenir.
 */
(function () {
  var KIT_VERSION = "1";
  var T = function (s) { return (s || "").replace(/\s+/g, " ").trim(); };
  var F = function (s) {
    return T(s).toLocaleUpperCase("tr-TR").replace(/İ/g, "I").replace(/Ş/g, "S").replace(/Ğ/g, "G")
      .replace(/Ü/g, "U").replace(/Ö/g, "O").replace(/Ç/g, "C");
  };
  var param = function (name) {
    var m = new RegExp("[?&]" + name + "=([^&#]*)", "i").exec(location.href);
    return m ? decodeURIComponent(m[1]) : null;
  };
  function cellText(c) {
    // keep line breaks inside a cell as " | " (e.g. "Ç:Normal | 3.3")
    var t = (c.innerText || c.textContent || "").split(/\n+/).map(T).filter(Boolean);
    return t.join(" | ");
  }
  function headerOf(table) {
    var tr = table.querySelector("thead tr") || table.querySelector("tr");
    if (!tr) return [];
    return Array.prototype.map.call(tr.children, function (c) { return T(c.innerText || c.textContent); });
  }
  function findTable(required) {
    var tables = document.querySelectorAll("table");
    for (var i = 0; i < tables.length; i++) {
      var h = headerOf(tables[i]).map(F);
      var ok = required.every(function (r) { return h.indexOf(r) >= 0; });
      if (ok) return tables[i];
    }
    return null;
  }
  function download(name, obj) {
    var blob = new Blob([JSON.stringify(obj, null, 1)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  function toast(msg, isError) {
    var d = document.createElement("div");
    d.textContent = msg;
    d.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;max-width:420px;padding:12px 16px;" +
      "font:14px/1.4 system-ui,sans-serif;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.3);color:#fff;background:" +
      (isError ? "#b3261e" : "#1b6e3c");
    document.body.appendChild(d);
    setTimeout(function () { d.remove(); }, 6000);
  }
  function infoFields() {
    // label : value pairs of the "At Bilgileri" block, read from the page text
    var text = document.body.innerText || "";
    var labels = ["İsim", "Yaş", "Doğ. Trh", "Handikap P.", "Baba", "Anne", "Antrenör", "Gerçek Sahip",
      "Üzerine Koşan Sahip", "Yetiştirici"];
    var out = {};
    labels.forEach(function (l) {
      var re = new RegExp("(?:^|\\n)[ \\t]*" + l.replace(/\./g, "\\.") + "[ \\t]*\\n?[ \\t]*:[ \\t]*\\n?[ \\t]*([^\\n\\t]+)");
      var m = re.exec(text);
      if (m) out[l] = T(m[1]);
    });
    return out;
  }

  function saveHorse() {
    var table = findTable(["TARIH", "DERECE"]);
    if (!table) { toast("Koşu geçmişi tablosu bulunamadı. Sayfa tamamen yüklendi mi?", true); return; }
    var header = headerOf(table);
    var rows = [];
    var trs = table.querySelectorAll("tbody tr");
    if (!trs.length) trs = table.querySelectorAll("tr");
    Array.prototype.forEach.call(trs, function (tr, i) {
      if (!table.querySelector("thead") && i === 0) return;
      var cells = Array.prototype.map.call(tr.children, cellText);
      if (cells.length < Math.min(6, header.length)) return;
      var links = Array.prototype.map.call(tr.querySelectorAll("a[href]"), function (a) {
        return { text: T(a.innerText || a.textContent), href: a.href };
      });
      rows.push({ cells: cells, links: links });
    });
    var info = infoFields();
    var atId = param("QueryParameter_AtId") || param("AtId");
    var title = document.querySelector("h1,h2,h3");
    var name = info["İsim"] || (title ? T(title.innerText) : "") || "AT";
    var filters = Array.prototype.map.call(document.querySelectorAll("select"), function (s) {
      var o = s.options[s.selectedIndex]; return o ? T(o.text) : "";
    });
    var obj = {
      kind: "TJK_AT_KOSU_BILGILERI", kit_version: KIT_VERSION, saved_at: new Date().toISOString(),
      url: location.href, at_id: atId, name: name, info: info, filters: filters,
      header: header, rows: rows,
    };
    var safe = F(name).replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "");
    download("tjk-at-" + (atId || "x") + "-" + safe + ".json", obj);
    var warn = filters.filter(function (f) { return f && !/^T[üu]m|^Mesafe$/i.test(f); });
    toast(name + ": " + rows.length + " koşu kaydedildi." + (warn.length ? " Dikkat: filtre seçili (" + warn.join(", ") + ")." : ""), false);
  }

  function listRaceHorses() {
    var seen = {}, races = [];
    var tables = document.querySelectorAll("table");
    Array.prototype.forEach.call(tables, function (t) {
      var links = t.querySelectorAll("a[href*='AtId=']");
      if (!links.length) return;
      // nearest "N. Koşu" text above the table
      var label = "", el = t;
      for (var k = 0; k < 60 && el && !label; k++) {
        el = el.previousElementSibling || el.parentElement;
        if (el && /\d+\s*\.\s*Ko[sş]u/i.test(el.innerText || "")) {
          var m = /(\d+)\s*\.\s*Ko[sş]u[^\n]*/i.exec(el.innerText); label = m ? T(m[0]).slice(0, 80) : "";
        }
      }
      var horses = [];
      Array.prototype.forEach.call(links, function (a) {
        var m = /AtId=(\d+)/i.exec(a.href);
        if (!m || seen[m[1]]) return;
        seen[m[1]] = 1;
        horses.push({ at_id: m[1], name: T(a.innerText || a.textContent),
          url: location.origin + "/TR/YarisSever/Query/ConnectedPage/AtKosuBilgileri?1=1&QueryParameter_AtId=" + m[1] });
      });
      if (horses.length) races.push({ label: label || ("Tablo " + (races.length + 1)), horses: horses });
    });
    if (!races.length) { toast("Bu sayfada at bağlantısı bulunamadı. Bir hipodrom sekmesi açık mı?", true); return; }
    var old = document.getElementById("horseiq-kit"); if (old) old.remove();
    var box = document.createElement("div");
    box.id = "horseiq-kit";
    box.style.cssText = "position:fixed;z-index:2147483647;top:12px;right:12px;width:360px;max-height:85vh;overflow:auto;" +
      "background:#fff;color:#111;border:1px solid #999;border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.3);" +
      "font:13px/1.45 system-ui,sans-serif;padding:12px";
    var html = "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px'>" +
      "<b>HorseIQ – at sayfaları</b><a href='#' data-x style='text-decoration:none;font-size:18px'>×</a></div>" +
      "<div style='color:#555;margin-bottom:8px'>Bir atın adına tıkla (yeni sekmede açılır), o sayfada HorseIQ butonuna bas. " +
      "Açtığın bağlantılar işaretlenir.</div>";
    races.forEach(function (r) {
      html += "<div style='margin:8px 0 2px;font-weight:600'>" + r.label.replace(/</g, "&lt;") + "</div>";
      r.horses.forEach(function (h) {
        html += "<div><a target='_blank' rel='noopener' href='" + h.url + "' data-h>" + (h.name || h.at_id).replace(/</g, "&lt;") +
          "</a> <span style='color:#888'>#" + h.at_id + "</span></div>";
      });
    });
    box.innerHTML = html;
    box.querySelector("[data-x]").onclick = function (e) { e.preventDefault(); box.remove(); };
    Array.prototype.forEach.call(box.querySelectorAll("[data-h]"), function (a) {
      a.addEventListener("click", function () { a.style.color = "#888"; a.insertAdjacentText("afterend", " ✓"); });
    });
    document.body.appendChild(box);
  }

  try {
    if (!/tjk\.org$/i.test(location.hostname) && !/^(localhost|127\.0\.0\.1|)$/.test(location.hostname)) {
      toast("Bu buton yalnızca tjk.org sayfalarında çalışır.", true); return;
    }
    if (/AtKosuBilgileri/i.test(location.href) || findTable(["TARIH", "DERECE"])) saveHorse();
    else listRaceHorses();
  } catch (e) {
    toast("HorseIQ hata: " + e.message, true);
  }
})();
