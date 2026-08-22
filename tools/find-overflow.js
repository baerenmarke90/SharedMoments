/* In der DevTools-Konsole auf der betroffenen Seite einfuegen.
 *
 * Listet jedes Element auf, das ueber den rechten Rand des Viewports
 * hinausragt - also die tatsaechliche Ursache fuer waagerechtes Scrollen.
 * Ausgegeben wird der aeusserste Verursacher zuerst, mit Selektor, Breite
 * und den Pixeln, die er zu weit rechts endet.
 *
 * Aufruf ohne Argumente prueft den Body-Bereich:
 *    findOverflow()
 */
(() => {
  const viewport = document.documentElement.clientWidth;
  const hits = [];

  document.querySelectorAll('body *').forEach((element) => {
    const style = getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') return;

    const box = element.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) return;

    // Feste Elemente haengen am Viewport und koennen das Dokument nicht dehnen.
    if (style.position === 'fixed') return;

    const overshoot = Math.round(box.right + window.scrollX - viewport);
    if (overshoot > 1) {
      hits.push({
        overshoot,
        width: Math.round(box.width),
        selector:
          element.tagName.toLowerCase() +
          (element.id ? '#' + element.id : '') +
          (element.className && typeof element.className === 'string'
            ? '.' + element.className.trim().split(/\s+/).join('.')
            : ''),
        element,
      });
    }
  });

  if (!hits.length) {
    console.log('Kein waagerechter Ueberlauf. Viewport:', viewport + 'px');
    return;
  }

  hits.sort((a, b) => b.overshoot - a.overshoot);
  console.log('Viewport:', viewport + 'px — Verursacher (weiteste zuerst):');
  console.table(hits.slice(0, 15).map(({ overshoot, width, selector }) => ({
    'zu weit rechts (px)': overshoot,
    'Breite (px)': width,
    Element: selector,
  })));
  console.log('Aeusserster Verursacher:', hits[0].element);
  hits[0].element.style.outline = '3px solid red';
})();
