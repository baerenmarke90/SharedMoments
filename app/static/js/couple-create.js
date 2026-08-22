/* Zentrales Erstellen-Menue der Couples-Oberflaeche.
 *
 * Bewusst nicht in home.js: das Sheet wird auf jeder Couples-Seite
 * eingebunden, home.js (91 KB) laedt aber nur auf /home, /memories und
 * /milestones. Frueher musste das "+" der Bottom-Nav deshalb erst nach
 * /home navigieren, um ein Sheet zu oeffnen.
 */
(function () {
   'use strict';

   const DIALOG_ID = 'dialog-couple-create';
   const DIALOG_SELECTOR = '#' + DIALOG_ID;
   const DISMISS_DISTANCE = 44;
   const REOPEN_DELAY = 180;

   // Zieltyp -> Element, das die gleiche Aktion lokal erledigt. Ist es auf
   // der aktuellen Seite vorhanden, wird direkt geoeffnet statt neu geladen.
   const LOCAL_TARGETS = {
      memory: '#dialog-create-new-home-item',
      milestone: '#dialog-create-new-timeline-item',
      plan: '#dialog-create-plan',
      chapter: '#dialog-create-chapter',
      place: '#dialog-create-place',
      bucket: '#bucket-quick-add'
   };

   function dialogElement() {
      return document.getElementById(DIALOG_ID);
   }

   function openUi(selector) {
      if (typeof window.callUi === 'function') window.callUi(selector);
   }

   function isCoupleCreateMenuOpen() {
      const dialog = dialogElement();
      if (!dialog) return false;
      return dialog.classList.contains('active') || dialog.hasAttribute('open');
   }

   function closeCoupleCreateMenu() {
      const dialog = dialogElement();
      if (!dialog) return;

      dialog.style.transform = '';
      dialog.classList.remove('couple-create-dragging');

      if (dialog.classList.contains('active')) {
         openUi(DIALOG_SELECTOR);
         return;
      }

      if (dialog.hasAttribute('open') && typeof dialog.close === 'function') {
         dialog.close();
      }
   }

   function openCoupleCreateMenu() {
      const dialog = dialogElement();

      // Fallback fuer Seiten ohne eingebundenes Sheet.
      if (!dialog) {
         window.location.href = '/home?create=1';
         return;
      }

      if (isCoupleCreateMenuOpen()) return;
      dialog.style.transform = '';
      openUi(DIALOG_SELECTOR);
   }

   function openLocalTarget(type) {
      if (type === 'bucket') {
         const input = document.getElementById('bucket-quick-add');
         if (!input) return;
         input.scrollIntoView({ behavior: 'smooth', block: 'center' });
         input.focus();
         return;
      }

      if (type === 'memory' && typeof window.openCreateDialog === 'function') {
         window.openCreateDialog();
         return;
      }

      if (type === 'place' && typeof window.openPlaceCreateDialog === 'function') {
         window.openPlaceCreateDialog();
         return;
      }

      openUi(LOCAL_TARGETS[type]);
   }

   function handleItemClick(event) {
      const item = event.target.closest('[data-couple-create]');
      if (!item) return;

      const type = item.dataset.coupleCreate;
      const selector = LOCAL_TARGETS[type];
      const localTarget = selector ? document.querySelector(selector) : null;

      if (!localTarget) {
         // Kein passendes Ziel auf dieser Seite: der Link navigiert.
         closeCoupleCreateMenu();
         return;
      }

      event.preventDefault();
      closeCoupleCreateMenu();

      // Mobile Browser verwerfen den zweiten Dialog, wenn im selben Klick
      // einer geschlossen und einer geoeffnet wird.
      window.setTimeout(() => openLocalTarget(type), REOPEN_DELAY);
   }

   function initDragToDismiss(dialog) {
      const dragZone = document.getElementById('couple-create-drag-zone');
      if (!dragZone) return;

      let startY = null;
      let currentY = null;
      let pointerId = null;

      dragZone.addEventListener('pointerdown', (event) => {
         // Der Schliessen-Button bleibt ein normales Tap-Ziel.
         if (event.target.closest('button, a, input, textarea, select')) return;

         startY = event.clientY;
         currentY = event.clientY;
         pointerId = event.pointerId;
         dialog.classList.add('couple-create-dragging');

         if (dragZone.setPointerCapture) dragZone.setPointerCapture(event.pointerId);
      });

      dragZone.addEventListener('pointermove', (event) => {
         if (startY === null || event.pointerId !== pointerId) return;

         currentY = event.clientY;
         dialog.style.transform = `translateY(${Math.max(0, currentY - startY)}px)`;
      });

      const finishDrag = (event) => {
         if (startY === null) return;
         if (event && pointerId !== null && event.pointerId !== pointerId) return;

         const distance = Math.max(0, (currentY ?? startY) - startY);
         startY = null;
         currentY = null;
         pointerId = null;
         dialog.classList.remove('couple-create-dragging');

         if (distance >= DISMISS_DISTANCE) {
            dialog.style.transform = 'translateY(110%)';
            window.setTimeout(closeCoupleCreateMenu, 120);
         } else {
            dialog.style.transform = '';
         }
      };

      dragZone.addEventListener('pointerup', finishDrag);
      dragZone.addEventListener('pointercancel', finishDrag);
   }

   function consumeCreateQuery(dialog) {
      const target = dialog.dataset.createQuery || 'none';
      if (target === 'none') return;

      const params = new URLSearchParams(window.location.search);
      if (params.get('create') !== '1') return;

      params.delete('create');
      const query = params.toString();
      window.history.replaceState({}, '', window.location.pathname
         + (query ? `?${query}` : '')
         + window.location.hash);

      window.setTimeout(() => {
         if (target === 'sheet') openCoupleCreateMenu();
         else openLocalTarget(target);
      }, 80);
   }

   function init() {
      const dialog = dialogElement();
      if (!dialog || dialog.dataset.createReady === '1') return;
      dialog.dataset.createReady = '1';

      // Native Dialog-Backdrops feuern den Klick auf dem Dialog selbst.
      dialog.addEventListener('click', (event) => {
         if (event.target === dialog) closeCoupleCreateMenu();
      });

      dialog.addEventListener('click', handleItemClick);

      initDragToDismiss(dialog);
      consumeCreateQuery(dialog);
   }

   window.openCoupleCreateMenu = openCoupleCreateMenu;
   window.closeCoupleCreateMenu = closeCoupleCreateMenu;
   window.isCoupleCreateMenuOpen = isCoupleCreateMenuOpen;

   if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
   } else {
      init();
   }
})();
