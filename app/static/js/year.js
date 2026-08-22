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

      function updateStatus() {
         if (!status) return;
         const first = index + 1;
         const last = Math.min(index + visibleCount(), items.length);
         status.textContent = `${first}–${last} / ${items.length}`;
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
         const max = maxIndex();
         index = index <= 0 ? max : index - 1;
         direction = -1;
         updatePosition();
         restartAutoPlay();
      });

      nextButton?.addEventListener('click', () => {
         const max = maxIndex();
         index = index >= max ? 0 : index + 1;
         direction = 1;
         updatePosition();
         restartAutoPlay();
      });

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
