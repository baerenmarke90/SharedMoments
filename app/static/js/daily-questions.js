(() => {
   'use strict';

   const ROOT_ID = 'daily-question-section';
   const DIALOG_ID = 'daily-question-dialog';

   let state = null;
   let pollTimer = null;

   function isCoupleHome() {
      return document.querySelector('.couple-home')
         && window.currentEdition === 'couples'
         && !window.ownItemsOnly;
   }

   function createCard() {
      if (document.getElementById(ROOT_ID)) {
         return document.getElementById(ROOT_ID);
      }

      const section = document.createElement('section');
      section.id = ROOT_ID;
      section.className = 'couple-section daily-question-section';
      section.innerHTML = `
         <article class="surface-container daily-question-card">
            <div class="daily-question-card-inner">
               <div class="daily-question-head">
                  <span class="daily-question-icon" aria-hidden="true">
                     <i>local_florist</i>
                  </span>
                  <div class="daily-question-heading">
                     <strong>Frage des Tages</strong>
                     <div class="daily-question-category" data-dq-category>Wird geladen …</div>
                  </div>
               </div>
               <p class="daily-question-text" data-dq-question>Frage wird geladen …</p>
               <div class="daily-question-status" data-dq-status style="display:none;"></div>
               <div class="daily-question-actions">
                  <a href="/questions">Unsere Fragen</a>
                  <button type="button" class="round" data-dq-primary disabled>
                     <i>edit</i>
                     <span>Antworten</span>
                  </button>
               </div>
            </div>
         </article>
      `;

      const home = document.querySelector('.couple-home');
      const thinkingCard = home.querySelector('.couple-thinking-card');

      if (thinkingCard) {
         const wrapper = thinkingCard.closest('.couple-section')
            || thinkingCard.closest('article')
            || thinkingCard;
         wrapper.insertAdjacentElement('afterend', section);
      } else {
         const hero = home.querySelector('.couple-hero');
         if (hero) {
            hero.insertAdjacentElement('afterend', section);
         } else {
            home.prepend(section);
         }
      }

      section.querySelector('[data-dq-primary]').addEventListener('click', openDialog);
      return section;
   }

   function createDialog() {
      if (document.getElementById(DIALOG_ID)) {
         return document.getElementById(DIALOG_ID);
      }

      const dialog = document.createElement('dialog');
      dialog.className = 'modal';
      dialog.id = DIALOG_ID;
      dialog.innerHTML = `
         <nav>
            <h5 class="max">Frage des Tages</h5>
            <button type="button" class="circle transparent" data-dq-close aria-label="Schließen">
               <i>close</i>
            </button>
         </nav>
         <p class="daily-question-dialog-question" data-dq-dialog-question></p>

         <div data-dq-edit-view>
            <form class="daily-question-dialog-form" data-dq-form>
               <div class="field label border extra">
                  <textarea name="answer" maxlength="500" required data-dq-textarea></textarea>
                  <label>Deine Antwort</label>
               </div>
               <div class="daily-question-dialog-meta">
                  <span>Die andere Antwort bleibt bis zum gemeinsamen Reveal verborgen.</span>
                  <span data-dq-count>0 / 500</span>
               </div>
               <nav class="right-align daily-question-dialog-actions">
                  <button type="button" class="transparent link" data-dq-cancel>Abbrechen</button>
                  <button type="submit">
                     <i>send</i>
                     <span>Speichern</span>
                  </button>
               </nav>
            </form>
         </div>

         <div data-dq-reveal-view style="display:none;">
            <div class="daily-question-reveal-grid" data-dq-reveal-grid></div>
            <nav class="right-align daily-question-dialog-actions">
               <a class="button transparent" href="/questions">Alle Fragen ansehen</a>
               <button type="button" data-dq-done>Schließen</button>
            </nav>
         </div>
      `;
      document.body.appendChild(dialog);

      const textarea = dialog.querySelector('[data-dq-textarea]');
      textarea.addEventListener('input', () => {
         dialog.querySelector('[data-dq-count]').textContent = `${textarea.value.length} / 500`;
      });

      dialog.querySelector('[data-dq-close]').addEventListener('click', () => dialog.close());
      dialog.querySelector('[data-dq-cancel]').addEventListener('click', () => dialog.close());
      dialog.querySelector('[data-dq-done]').addEventListener('click', () => dialog.close());
      dialog.querySelector('[data-dq-form]').addEventListener('submit', submitAnswer);

      return dialog;
   }

   function setStatus(icon, text) {
      const root = document.getElementById(ROOT_ID);
      if (!root) return;
      const el = root.querySelector('[data-dq-status]');
      if (!text) {
         el.style.display = 'none';
         el.replaceChildren();
         return;
      }

      const iconEl = document.createElement('i');
      iconEl.textContent = icon;
      const span = document.createElement('span');
      span.textContent = text;
      el.replaceChildren(iconEl, span);
      el.style.display = 'flex';
   }

   function renderCard() {
      const root = document.getElementById(ROOT_ID);
      if (!root || !state) return;

      root.querySelector('[data-dq-question]').textContent = state.question;
      root.querySelector('[data-dq-category]').textContent = state.category_label || 'Gemeinsam';
      const button = root.querySelector('[data-dq-primary]');
      const buttonIcon = button.querySelector('i');
      const buttonText = button.querySelector('span');

      button.disabled = false;

      if (state.revealed) {
         setStatus('favorite', 'Eure Antworten sind da.');
         buttonIcon.textContent = 'visibility';
         buttonText.textContent = 'Gemeinsam ansehen';
      } else if (state.own_answered) {
         const partnerName = state.partner && state.partner.first_name
            ? state.partner.first_name
            : 'deinen Partner';
         setStatus(
            'hourglass_top',
            `Deine Antwort ist gespeichert. Warte noch auf ${partnerName}.`
         );
         buttonIcon.textContent = 'edit';
         buttonText.textContent = 'Antwort bearbeiten';
      } else {
         setStatus('lock', 'Ihr antwortet unabhängig voneinander.');
         buttonIcon.textContent = 'edit';
         buttonText.textContent = 'Antworten';
      }

      schedulePolling();
   }

   function renderDialog() {
      if (!state) return;

      const dialog = createDialog();
      dialog.querySelector('[data-dq-dialog-question]').textContent = state.question;

      const editView = dialog.querySelector('[data-dq-edit-view]');
      const revealView = dialog.querySelector('[data-dq-reveal-view]');

      if (state.revealed) {
         editView.style.display = 'none';
         revealView.style.display = 'block';

         const grid = dialog.querySelector('[data-dq-reveal-grid]');
         grid.replaceChildren();

         for (const answer of state.answers || []) {
            const card = document.createElement('div');
            card.className = 'daily-question-reveal-answer';

            const author = document.createElement('div');
            author.className = 'daily-question-reveal-author';

            const img = document.createElement('img');
            img.src = `/api/v2/media/static/${encodeURIComponent(answer.profile_picture || 'profile-placeholder.jpg')}`;
            img.alt = '';

            const name = document.createElement('span');
            name.textContent = answer.first_name || 'Partner';

            const text = document.createElement('p');
            text.textContent = answer.answer || '';

            author.append(img, name);
            card.append(author, text);
            grid.appendChild(card);
         }
      } else {
         revealView.style.display = 'none';
         editView.style.display = 'block';

         const textarea = dialog.querySelector('[data-dq-textarea]');
         textarea.value = state.own_answer || '';
         dialog.querySelector('[data-dq-count]').textContent = `${textarea.value.length} / 500`;

         const submitText = dialog.querySelector('[data-dq-form] button[type="submit"] span');
         submitText.textContent = state.own_answered ? 'Aktualisieren' : 'Speichern';
      }
   }

   function openDialog() {
      if (!state) return;
      const dialog = createDialog();
      renderDialog();
      if (typeof dialog.showModal === 'function') {
         dialog.showModal();
      } else {
         dialog.setAttribute('open', '');
      }
   }

   async function submitAnswer(event) {
      event.preventDefault();
      if (!state) return;

      const form = event.currentTarget;
      const textarea = form.querySelector('[data-dq-textarea]');
      const answer = textarea.value.trim();

      if (!answer) {
         textarea.focus();
         return;
      }

      const submit = form.querySelector('button[type="submit"]');
      submit.disabled = true;

      try {
         const response = await fetch('/api/v2/daily-question/answer', {
            method: 'POST',
            headers: {
               'Accept': 'application/json',
               'Content-Type': 'application/json',
            },
            body: JSON.stringify({
               assignment_id: state.id,
               answer,
            }),
         });
         const payload = await response.json();

         if (!response.ok || payload.status !== 'success') {
            throw new Error(payload.message || 'Antwort konnte nicht gespeichert werden.');
         }

         const wasRevealed = Boolean(state.revealed);
         state = payload.data;
         renderCard();
         renderDialog();

         if (!wasRevealed && state.revealed) {
            celebrateReveal();
         } else {
            const dialog = document.getElementById(DIALOG_ID);
            if (dialog && dialog.open) {
               dialog.close();
            }
         }
      } catch (error) {
         window.alert(error.message || 'Antwort konnte nicht gespeichert werden.');
      } finally {
         submit.disabled = false;
      }
   }

   function celebrateReveal() {
      if (!state || !state.revealed) return;

      const key = `sharedmoments-daily-question-reveal-${state.id}`;
      if (window.localStorage.getItem(key)) return;
      window.localStorage.setItem(key, '1');

      const celebration = document.createElement('div');
      celebration.className = 'daily-question-celebration';
      celebration.innerHTML = '<i>local_florist</i><strong>Eure Antworten sind da</strong>';
      document.body.appendChild(celebration);

      requestAnimationFrame(() => celebration.classList.add('active'));
      window.setTimeout(() => celebration.remove(), 2800);

      try {
         if (navigator.vibrate) navigator.vibrate(40);
      } catch (error) {
         // Haptics are optional.
      }
   }

   function removeFeatureUi() {
      const root = document.getElementById(ROOT_ID);
      if (root) root.remove();

      const dialog = document.getElementById(DIALOG_ID);
      if (dialog) dialog.remove();

      if (pollTimer) {
         window.clearInterval(pollTimer);
         pollTimer = null;
      }
      state = null;
   }

   async function loadState({ silent = false } = {}) {
      try {
         const response = await fetch('/api/v2/daily-question', {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
         });
         const payload = await response.json();

         if (payload && payload.feature_disabled) {
            removeFeatureUi();
            return;
         }

         if (!response.ok || payload.status !== 'success') {
            throw new Error(payload.message || 'Frage konnte nicht geladen werden.');
         }

         const wasRevealed = Boolean(state && state.revealed);
         state = payload.data;
         renderCard();

         if (!wasRevealed && state.revealed) {
            celebrateReveal();
         }
      } catch (error) {
         if (!silent) {
            setStatus('error', 'Die Frage des Tages konnte gerade nicht geladen werden.');
         }
         console.warn('[Daily Questions]', error);
      }
   }

   function schedulePolling() {
      if (pollTimer) {
         window.clearInterval(pollTimer);
         pollTimer = null;
      }

      if (state && state.own_answered && !state.revealed) {
         pollTimer = window.setInterval(() => loadState({ silent: true }), 12000);
      }
   }

   function init() {
      if (!isCoupleHome()) return;

      createCard();
      createDialog();
      loadState();

      document.addEventListener('visibilitychange', () => {
         if (!document.hidden) {
            loadState({ silent: true });
         }
      });
   }

   if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init, { once: true });
   } else {
      init();
   }
})();
