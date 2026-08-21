let currentHeartMomentFilter = 'all';
let currentHeartMoments = [];
let heartSnackbarTimer = null;


function localDateISO() {
    const now = new Date();

    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');

    return `${year}-${month}-${day}`;
}


function showHeartSnackbar(message, error = false) {
    const snackbar = document.getElementById('heart-moments-snackbar');
    const text = document.getElementById('heart-moments-snackbar-text');

    if (!snackbar || !text) {
        return;
    }

    text.textContent = message;

    snackbar.classList.remove('error');

    if (error) {
        snackbar.classList.add('error');
    }

    snackbar.classList.add('active');

    if (heartSnackbarTimer) {
        clearTimeout(heartSnackbarTimer);
    }

    heartSnackbarTimer = setTimeout(() => {
        snackbar.classList.remove('active');
    }, 4000);
}


function feelingIcon(feeling) {
    const icons = {
        loved: 'favorite',
        seen: 'visibility',
        appreciated: 'workspace_premium',
        supported: 'volunteer_activism',
        grateful: 'sentiment_satisfied',
        happy: 'mood'
    };

    return icons[feeling] || 'favorite';
}


function feelingLabel(feeling) {
    return (
        window.heartMomentText.feelings[feeling]
        || feeling
        || ''
    );
}


function formatMomentDate(value) {
    if (!value) {
        return '';
    }

    const date = new Date(`${value}T00:00:00`);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleDateString();
}


function setHeartMomentFilter(filter, button) {
    currentHeartMomentFilter = filter;

    document
        .querySelectorAll('.heart-filter')
        .forEach(element => element.classList.remove('fill'));

    if (button) {
        button.classList.add('fill');
    }

    loadHeartMoments();
}


async function loadHeartMoments() {
    const loading = document.getElementById('heart-moments-loading');
    const empty = document.getElementById('heart-moments-empty');
    const list = document.getElementById('heart-moments-list');

    loading.style.display = '';
    empty.style.display = 'none';
    list.innerHTML = '';

    try {
        const response = await fetch(
            `/api/v2/heart-moments?filter=${encodeURIComponent(currentHeartMomentFilter)}`
        );

        const result = await response.json();

        if (!response.ok || result.status !== 'success') {
            throw new Error(result.message || window.heartMomentText.loadError);
        }

        currentHeartMoments = result.data.items || [];

        renderHeartMoments();

    } catch (error) {
        console.error('[HeartMoments] Load failed:', error);

        showHeartSnackbar(
            window.heartMomentText.loadError,
            true
        );

    } finally {
        loading.style.display = 'none';
    }
}


function renderHeartMoments() {
    const list = document.getElementById('heart-moments-list');
    const empty = document.getElementById('heart-moments-empty');

    list.innerHTML = '';

    if (!currentHeartMoments.length) {
        empty.style.display = '';
        return;
    }

    empty.style.display = 'none';

    currentHeartMoments.forEach(moment => {
        list.appendChild(createHeartMomentCard(moment));
    });
}


function createHeartMomentCard(moment) {
    const article = document.createElement('article');

    article.className = 'surface-container padding heart-moment-card';

    const header = document.createElement('div');
    header.className = 'row';

    const feelingIconElement = document.createElement('i');
    feelingIconElement.className = 'circle';
    feelingIconElement.textContent = feelingIcon(moment.feeling);

    const titleArea = document.createElement('div');
    titleArea.className = 'max';

    const feelingTitle = document.createElement('h6');
    feelingTitle.className = 'small';
    feelingTitle.textContent = feelingLabel(moment.feeling);

    const meta = document.createElement('div');
    meta.className = 'heart-moment-meta small-text';

    const dateElement = document.createElement('span');
    dateElement.textContent = formatMomentDate(moment.momentDate);

    meta.appendChild(dateElement);

    if (moment.author) {
        const authorElement = document.createElement('span');

        const authorName = [
            moment.author.firstName,
            moment.author.lastName
        ]
            .filter(Boolean)
            .join(' ');

        authorElement.textContent = authorName;

        meta.appendChild(authorElement);
    }

    const visibilityElement = document.createElement('span');

    visibilityElement.textContent =
        moment.visibility === 'private'
            ? `🔒 ${window.heartMomentText.private}`
            : `♡ ${window.heartMomentText.shared}`;

    meta.appendChild(visibilityElement);

    titleArea.appendChild(feelingTitle);
    titleArea.appendChild(meta);

    header.appendChild(feelingIconElement);
    header.appendChild(titleArea);

    const ownMoment =
        Number(moment.authorUserID)
        === Number(window.currentHeartMomentUserId);

    if (ownMoment) {
        const actions = document.createElement('div');
        actions.className = 'heart-moment-actions';

        const editButton = document.createElement('button');
        editButton.className = 'circle transparent';
        editButton.type = 'button';

        const editIcon = document.createElement('i');
        editIcon.textContent = 'edit';

        editButton.appendChild(editIcon);

        editButton.addEventListener('click', () => {
            openEditHeartMoment(moment.id);
        });

        const deleteButton = document.createElement('button');
        deleteButton.className = 'circle transparent';
        deleteButton.type = 'button';

        const deleteIcon = document.createElement('i');
        deleteIcon.textContent = 'delete';

        deleteButton.appendChild(deleteIcon);

        deleteButton.addEventListener('click', () => {
            deleteHeartMoment(moment.id);
        });

        actions.appendChild(editButton);
        actions.appendChild(deleteButton);

        header.appendChild(actions);
    }

    article.appendChild(header);

    const description = document.createElement('p');
    description.className = 'heart-moment-description';
    description.textContent = moment.description || '';

    article.appendChild(description);

    return article;
}


function openCreateHeartMoment() {
    document.getElementById('heart-create-date').value = localDateISO();
    document.getElementById('heart-create-description').value = '';
    document.getElementById('heart-create-feeling').value = 'seen';
    document.getElementById('heart-create-visibility').value = 'shared';

    callUi('#dialog-create-heart-moment');
}


async function saveHeartMoment() {
    const description =
        document
            .getElementById('heart-create-description')
            .value
            .trim();

    if (!description) {
        showHeartSnackbar(
            window.heartMomentText.descriptionRequired,
            true
        );

        return;
    }

    const payload = {
        momentDate:
            document.getElementById('heart-create-date').value,

        description,

        feeling:
            document.getElementById('heart-create-feeling').value,

        visibility:
            document.getElementById('heart-create-visibility').value
    };

    try {
        const response = await fetch('/api/v2/heart-moments', {
            method: 'POST',

            headers: {
                'Content-Type': 'application/json'
            },

            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (!response.ok || result.status !== 'success') {
            throw new Error(
                result.message
                || window.heartMomentText.saveError
            );
        }

        callUi('#dialog-create-heart-moment');

        showHeartSnackbar(
            window.heartMomentText.created
        );

        await loadHeartMoments();

    } catch (error) {
        console.error('[HeartMoments] Create failed:', error);

        showHeartSnackbar(
            error.message || window.heartMomentText.saveError,
            true
        );
    }
}


function openEditHeartMoment(id) {
    const moment = currentHeartMoments.find(
        item => Number(item.id) === Number(id)
    );

    if (!moment) {
        return;
    }

    document.getElementById('heart-edit-id').value = moment.id;
    document.getElementById('heart-edit-date').value = moment.momentDate || '';
    document.getElementById('heart-edit-description').value = moment.description || '';
    document.getElementById('heart-edit-feeling').value = moment.feeling;
    document.getElementById('heart-edit-visibility').value = moment.visibility;

    callUi('#dialog-edit-heart-moment');
}


async function saveEditedHeartMoment() {
    const id =
        document.getElementById('heart-edit-id').value;

    const description =
        document
            .getElementById('heart-edit-description')
            .value
            .trim();

    if (!description) {
        showHeartSnackbar(
            window.heartMomentText.descriptionRequired,
            true
        );

        return;
    }

    const payload = {
        momentDate:
            document.getElementById('heart-edit-date').value,

        description,

        feeling:
            document.getElementById('heart-edit-feeling').value,

        visibility:
            document.getElementById('heart-edit-visibility').value
    };

    try {
        const response = await fetch(
            `/api/v2/heart-moments/${encodeURIComponent(id)}`,
            {
                method: 'PUT',

                headers: {
                    'Content-Type': 'application/json'
                },

                body: JSON.stringify(payload)
            }
        );

        const result = await response.json();

        if (!response.ok || result.status !== 'success') {
            throw new Error(
                result.message
                || window.heartMomentText.saveError
            );
        }

        callUi('#dialog-edit-heart-moment');

        showHeartSnackbar(
            window.heartMomentText.updated
        );

        await loadHeartMoments();

    } catch (error) {
        console.error('[HeartMoments] Update failed:', error);

        showHeartSnackbar(
            error.message || window.heartMomentText.saveError,
            true
        );
    }
}


async function deleteHeartMoment(id) {
    if (!window.confirm(window.heartMomentText.deleteConfirm)) {
        return;
    }

    try {
        const response = await fetch(
            `/api/v2/heart-moments/${encodeURIComponent(id)}`,
            {
                method: 'DELETE'
            }
        );

        const result = await response.json();

        if (!response.ok || result.status !== 'success') {
            throw new Error(
                result.message
                || window.heartMomentText.deleteError
            );
        }

        showHeartSnackbar(
            window.heartMomentText.deleted
        );

        await loadHeartMoments();

    } catch (error) {
        console.error('[HeartMoments] Delete failed:', error);

        showHeartSnackbar(
            error.message || window.heartMomentText.deleteError,
            true
        );
    }
}


document.addEventListener('DOMContentLoaded', () => {
    const createDate =
        document.getElementById('heart-create-date');

    if (createDate) {
        createDate.value = localDateISO();
    }

    loadHeartMoments();
});
