(() => {
   'use strict';

   const ROOT_ID = 'daily-question-section';
   const DIALOG_ID = 'daily-question-dialog';
   const MEMORY_ID = 'daily-question-memory';

   let state = null;
   let pollTimer = null;

   function isCoupleHome() {
      return (
         document.body.classList.contains('couple-page-home')
         && document.getElementById('div-render-couple-home-dashboard')
         && !window.ownItemsOnly
      );
   }

   async function fetchJson(url, options = {}) {
      const response = await fetch(url, {
         cache: 'no-store',
         ...options,
         headers: {
            'Accept': 'application/json',
            ...(options.headers || {}),
         },
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== 'success') {
         const error = new Error(payload.message || 'Anfrage fehlgeschlagen.');
         error.featureDisabled = Boolean(payload.feature_disabled);
         throw error;
      }
      return payload.data;
   }

   function createCard() {
      let section = document.getElementById(ROOT_ID);
      if (section) return section;

      section = document.createElement('section');
      section.id = ROOT_ID;
      section.className = 'couple-section daily-question-section';
      section.innerHTML = `
         <article class="surface-container daily-question-card">
            <div class="daily-question-card-inner">
               <div class="daily-question-head">
                  <span class="daily-question-icon" aria-hidden="true"><i>local_florist</i></span>
                  <div class="daily-question-heading">
                     <strong>Frage des Tages</strong>
                     <div class="daily-question-category" data-dq-category>Wird geladen …</div>
                  </div>
               </div>
               <p class="daily-question-text" data-dq-question>Frage wird geladen …</p>
               <div class="daily-question-status" data-dq-status hidden></div>
               <div class="daily-question-actions">
                  <a class="button transparent round" href="/questions">
                     <i>history</i><span>Unsere Fragen</span>
                  </a>
                  <button type="button" class="transparent round" data-dq-skip hidden>
                     <i>skip_next</i><span>Andere Frage</span>
                  </button>
                  <button type="button" class="round" data-dq-primary disabled>
                     <i>edit</i><span>Antworten</span>
                  </button>
               </div>
            </div>
         </article>
      `;

      const home = document.querySelector('.couple-home')
         || document.getElementById('div-render-couple-home-dashboard');
      if (!home) throw new Error('Couple dashboard container not found.');

      const thinkingCard = home.querySelector('.couple-thinking-card');
      if (thinkingCard) {
         const wrapper = thinkingCard.closest('.couple-section')
            || thinkingCard.closest('article')
            || thinkingCard;
         wrapper.insertAdjacentElement('afterend', section);
      } else {
         const hero = home.querySelector('.couple-hero');
         if (hero) hero.insertAdjacentElement('afterend', section);
         else home.prepend(section);
      }

      section.querySelector('[data-dq-primary]').addEventListener('click', openDialog);
      section.querySelector('[data-dq-skip]').addEventListener('click', skipQuestion);
      return section;
   }

   function createDialog() {
      let dialog = document.getElementById(DIALOG_ID);
      if (dialog) return dialog;

      dialog = document.createElement('dialog');
      dialog.className = 'modal daily-question-dialog';
      dialog.id = DIALOG_ID;
      dialog.innerHTML = `
         <nav>
            <h5 class="max">Frage des Tages</h5>
            <button type="button" class="circle transparent" data-dq-close aria-label="Schließen"><i>close</i></button>
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
                  <button type="submit"><i>send</i><span>Speichern</span></button>
               </nav>
            </form>
         </div>
         <div data-dq-reveal-view hidden>
            <div class="daily-question-reveal-grid" data-dq-reveal-grid></div>
            <nav class="right-align daily-question-dialog-actions">
               <a class="button transparent" href="/questions?status=answered">Alle Antworten ansehen</a>
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
         el.hidden = true;
         el.replaceChildren();
         return;
      }
      const iconEl = document.createElement('i');
      iconEl.textContent = icon;
      const span = document.createElement('span');
      span.textContent = text;
      el.replaceChildren(iconEl, span);
      el.hidden = false;
   }

   function renderCard() {
      const root = document.getElementById(ROOT_ID);
      if (!root || !state) return;

      root.querySelector('[data-dq-question]').textContent = state.question || '';
      root.querySelector('[data-dq-category]').textContent = state.category_label || '';

      const primary = root.querySelector('[data-dq-primary]');
      const primaryIcon = primary.querySelector('i');
      const primaryText = primary.querySelector('span');
      const skip = root.querySelector('[data-dq-skip]');

      primary.disabled = false;
      skip.hidden = !state.can_skip;

      if (state.revealed) {
         setStatus('favorite', 'Eure Antworten sind da.');
         primaryIcon.textContent = 'visibility';
         primaryText.textContent = 'Gemeinsam ansehen';
      } else if (state.own_answered) {
         setStatus('hourglass_top', 'Deine Antwort ist gespeichert. Warte noch auf die andere Antwort.');
         primaryIcon.textContent = 'edit';
         primaryText.textContent = 'Antwort bearbeiten';
      } else {
         setStatus('lock', 'Ihr antwortet unabhängig voneinander.');
         primaryIcon.textContent = 'edit';
         primaryText.textContent = 'Antworten';
      }

      schedulePolling();
   }

   function renderDialog() {
      if (!state) return;
      const dialog = createDialog();
      dialog.querySelector('[data-dq-dialog-question]').textContent = state.question || '';
      const editView = dialog.querySelector('[data-dq-edit-view]');
      const revealView = dialog.querySelector('[data-dq-reveal-view]');

      if (state.revealed) {
         editView.hidden = true;
         revealView.hidden = false;
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
            author.append(img, name);

            const text = document.createElement('p');
            text.textContent = answer.answer || '';
            card.append(author, text);
            grid.appendChild(card);
         }
      } else {
         revealView.hidden = true;
         editView.hidden = false;
         const textarea = dialog.querySelector('[data-dq-textarea]');
         textarea.value = state.own_answer || '';
         dialog.querySelector('[data-dq-count]').textContent = `${textarea.value.length} / 500`;
         dialog.querySelector('[data-dq-form] button[type="submit"] span').textContent = state.own_answered ? 'Aktualisieren' : 'Speichern';
      }
   }

   function openDialog() {
      if (!state) return;
      const dialog = createDialog();
      renderDialog();
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
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
         const previousRevealed = Boolean(state.revealed);
         state = await fetchJson('/api/v2/daily-question/answer', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({assignment_id: state.id, answer}),
         });
         renderCard();
         renderDialog();
         if (!previousRevealed && state.revealed) {
            celebrateReveal();
         } else {
            const dialog = document.getElementById(DIALOG_ID);
            if (dialog && dialog.open) dialog.close();
         }
      } catch (error) {
         window.alert(error.message || 'Antwort konnte nicht gespeichert werden.');
      } finally {
         submit.disabled = false;
      }
   }

   async function skipQuestion() {
      if (!state || !state.can_skip) return;
      if (!window.confirm('Diese Frage für euch beide überspringen und heute eine andere auswählen?')) return;

      const button = document.querySelector(`#${ROOT_ID} [data-dq-skip]`);
      if (button) button.disabled = true;
      try {
         state = await fetchJson('/api/v2/daily-question/skip', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({assignment_id: state.id}),
         });
         renderCard();
      } catch (error) {
         window.alert(error.message || 'Die Frage konnte nicht übersprungen werden.');
      } finally {
         if (button) button.disabled = false;
      }
   }

   function celebrateReveal() {
      if (!state || !state.revealed) return;
      const key = `sharedmoments-daily-question-reveal-${state.id}`;
      if (window.localStorage.getItem(key)) return;
      window.localStorage.setItem(key, '1');

      const celebration = document.createElement('div');
      celebration.className = 'daily-question-celebration';
      const icon = document.createElement('i');
      icon.textContent = 'local_florist';
      const text = document.createElement('strong');
      text.textContent = 'Eure Antworten sind da';
      celebration.append(icon, text);
      document.body.appendChild(celebration);
      requestAnimationFrame(() => celebration.classList.add('active'));
      window.setTimeout(() => celebration.remove(), 2800);

      try {
         if (navigator.vibrate) navigator.vibrate(40);
      } catch (_) {
         // Haptics are optional.
      }
   }

   function removeMemory() {
      const memory = document.getElementById(MEMORY_ID);
      if (memory) memory.remove();
   }

   function renderMemory(memory) {
      removeMemory();
      if (!memory || !memory.revealed || !(memory.answers || []).length) return;

      const current = document.getElementById(ROOT_ID);
      if (!current) return;

      const section = document.createElement('section');
      section.id = MEMORY_ID;
      section.className = 'couple-section daily-question-memory-section';

      const article = document.createElement('article');
      article.className = 'surface-container daily-question-memory-card';

      const heading = document.createElement('div');
      heading.className = 'daily-question-memory-heading';
      const icon = document.createElement('span');
      icon.className = 'daily-question-memory-icon';
      icon.innerHTML = '<i>history</i>';
      const copy = document.createElement('div');
      const strong = document.createElement('strong');
      strong.textContent = 'Vor einem Jahr';
      const date = document.createElement('span');
      date.textContent = 'Eine Frage aus eurer gemeinsamen Geschichte';
      copy.append(strong, date);
      heading.append(icon, copy);

      const question = document.createElement('p');
      question.className = 'daily-question-memory-question';
      question.textContent = memory.question || '';

      const answers = document.createElement('div');
      answers.className = 'daily-question-memory-answers';
      for (const answer of memory.answers || []) {
         const item = document.createElement('div');
         const name = document.createElement('strong');
         name.textContent = answer.first_name || 'Partner';
         const text = document.createElement('span');
         text.textContent = answer.answer || '';
         item.append(name, text);
         answers.appendChild(item);
      }

      const link = document.createElement('a');
      link.className = 'button transparent round daily-question-memory-link';
      link.href = `/questions?status=answered#question-${encodeURIComponent(memory.id)}`;
      link.innerHTML = '<i>arrow_forward</i><span>Antworten ansehen</span>';

      article.append(heading, question, answers, link);
      section.appendChild(article);
      current.insertAdjacentElement('afterend', section);
   }

   async function loadMemory() {
      try {
         const memory = await fetchJson('/api/v2/daily-question/memory');
         renderMemory(memory);
      } catch (error) {
         if (!error.featureDisabled) console.warn('[Daily Questions memory]', error);
      }
   }

   function removeFeatureUi() {
      document.getElementById(ROOT_ID)?.remove();
      document.getElementById(DIALOG_ID)?.remove();
      removeMemory();
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = null;
      state = null;
   }

   async function loadState({silent = false} = {}) {
      try {
         const previousRevealed = Boolean(state && state.revealed);
         state = await fetchJson('/api/v2/daily-question');
         renderCard();
         if (!previousRevealed && state.revealed) celebrateReveal();
      } catch (error) {
         if (error.featureDisabled) {
            removeFeatureUi();
            return;
         }
         if (!silent) setStatus('error', 'Die Frage des Tages konnte gerade nicht geladen werden.');
         console.warn('[Daily Questions]', error);
      }
   }

   function schedulePolling() {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = null;
      if (state && state.own_answered && !state.revealed) {
         pollTimer = window.setInterval(() => loadState({silent: true}), 12000);
      }
   }

   function init() {
      if (!isCoupleHome()) return;
      createCard();
      createDialog();
      loadState();
      loadMemory();

      document.addEventListener('visibilitychange', () => {
         if (!document.hidden) {
            loadState({silent: true});
            loadMemory();
         }
      });
   }

   if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init, {once: true});
   } else {
      init();
   }
})();
