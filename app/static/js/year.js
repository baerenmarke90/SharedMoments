(() => {
   function initYearCollage() {
      const shell = document.querySelector('[data-year-collage]');
      if (!shell) return;

      const track = shell.querySelector('.year-collage');
      const items = Array.from(shell.querySelectorAll('.year-collage-item'));
      const prevButton = shell.querySelector('[data-year-collage-prev]');
      const nextButton = shell.querySelector('[data-year-collage-next]');
      const status = shell.querySelector('[data-year-collage-status]');

      if (!track || items.length === 0) return;

      const visibleCount = () => Math.min(3, items.length);
      const maxIndex = () => Math.max(0, items.length - visibleCount());
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

      let index = 0;
      let direction = 1;
      let timer = null;
      let paused = false;

      // Nur manuelle Navigation wird angesagt. Sonst liest ein Screenreader
      // alle 4,2 Sekunden ungefragt den neuen Bildbereich vor.
      let announceNext = false;

      function updateStatus() {
         if (!status) return;
         const first = index + 1;
         const last = Math.min(index + visibleCount(), items.length);
         status.setAttribute('aria-live', announceNext ? 'polite' : 'off');
         status.textContent = `${first}–${last} / ${items.length}`;
         announceNext = false;
      }

      function goTo(nextIndex, dir) {
         const max = maxIndex();
         if (max <= 0) return;
         index = Math.max(0, Math.min(nextIndex, max));
         direction = dir;
         announceNext = true;
         updatePosition();
         restartAutoPlay();
      }

      function updatePosition(animate = true) {
         const target = items[index];
         if (!target) return;

         const offset = target.offsetLeft - items[0].offsetLeft;
         if (!animate) track.style.transition = 'none';
         track.style.transform = `translate3d(${-offset}px, 0, 0)`;
         updateStatus();

         if (!animate) {
            window.requestAnimationFrame(() => {
               track.style.transition = '';
            });
         }
      }

      function stopAutoPlay() {
         if (timer !== null) {
            window.clearInterval(timer);
            timer = null;
         }
      }

      function autoAdvance() {
         const max = maxIndex();
         if (max <= 0) return;

         if (index >= max) direction = -1;
         if (index <= 0) direction = 1;
         index += direction;
         updatePosition();
      }

      function startAutoPlay() {
         stopAutoPlay();
         if (paused || reducedMotion.matches || maxIndex() <= 0 || document.hidden) {
            return;
         }
         timer = window.setInterval(autoAdvance, 4200);
      }

      function restartAutoPlay() {
         stopAutoPlay();
         startAutoPlay();
      }

      prevButton?.addEventListener('click', () => {
         goTo(index <= 0 ? maxIndex() : index - 1, -1);
      });

      nextButton?.addEventListener('click', () => {
         goTo(index >= maxIndex() ? 0 : index + 1, 1);
      });

      // Wischen ist auf dem Handy die naheliegende Geste – bisher gab es nur
      // die beiden Pfeil-Buttons.
      let swipeStartX = null;
      let swipeStartY = null;

      track.addEventListener('touchstart', (event) => {
         if (event.touches.length !== 1) return;
         swipeStartX = event.touches[0].clientX;
         swipeStartY = event.touches[0].clientY;
         paused = true;
         stopAutoPlay();
      }, { passive: true });

      track.addEventListener('touchend', (event) => {
         const startX = swipeStartX;
         const startY = swipeStartY;
         swipeStartX = null;
         swipeStartY = null;
         paused = false;

         if (startX === null) {
            startAutoPlay();
            return;
         }

         const touch = event.changedTouches[0];
         const deltaX = touch.clientX - startX;
         const deltaY = touch.clientY - startY;

         // Horizontale Geste, aber kein versehentliches Scrollen und kein Tap
         // (sonst würde der Link auf dem Bild nicht mehr funktionieren).
         if (Math.abs(deltaX) < 40 || Math.abs(deltaX) < Math.abs(deltaY) * 1.5) {
            startAutoPlay();
            return;
         }

         if (deltaX < 0) goTo(index >= maxIndex() ? 0 : index + 1, 1);
         else goTo(index <= 0 ? maxIndex() : index - 1, -1);
      }, { passive: true });

      track.addEventListener('touchcancel', () => {
         swipeStartX = null;
         swipeStartY = null;
         paused = false;
         startAutoPlay();
      }, { passive: true });

      shell.addEventListener('mouseenter', () => {
         paused = true;
         stopAutoPlay();
      });
      shell.addEventListener('mouseleave', () => {
         paused = false;
         startAutoPlay();
      });
      shell.addEventListener('focusin', () => {
         paused = true;
         stopAutoPlay();
      });
      shell.addEventListener('focusout', () => {
         window.setTimeout(() => {
            if (!shell.contains(document.activeElement)) {
               paused = false;
               startAutoPlay();
            }
         }, 0);
      });

      document.addEventListener('visibilitychange', () => {
         if (document.hidden) stopAutoPlay();
         else startAutoPlay();
      });

      reducedMotion.addEventListener?.('change', startAutoPlay);

      let resizeTimer = null;
      window.addEventListener('resize', () => {
         window.clearTimeout(resizeTimer);
         resizeTimer = window.setTimeout(() => {
            index = Math.min(index, maxIndex());
            updatePosition(false);
         }, 120);
      });

      updatePosition(false);
      startAutoPlay();
   }

   if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initYearCollage);
   } else {
      initYearCollage();
   }
})();
