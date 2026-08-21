let currentHeartMomentFilter = 'all';
let currentHeartMoments = [];

const heartMomentHighlightId =
    new URLSearchParams(
        window.location.search
    ).get('highlight');

let heartSnackbarTimer = null;

let createImageObjectUrl = null;
let editImageObjectUrl = null;

let editRemoveImage = false;


function localDateISO() {
    const now = new Date();

    const year = now.getFullYear();

    const month = String(
        now.getMonth() + 1
    ).padStart(2, '0');

    const day = String(
        now.getDate()
    ).padStart(2, '0');

    return `${year}-${month}-${day}`;
}


function showHeartSnackbar(
    message,
    error = false
) {
    const snackbar = document.getElementById(
        'heart-moments-snackbar'
    );

    const text = document.getElementById(
        'heart-moments-snackbar-text'
    );

    if (!snackbar || !text) {
        return;
    }

    text.textContent = message;

    snackbar.classList.remove(
        'error'
    );

    if (error) {
        snackbar.classList.add(
            'error'
        );
    }

    snackbar.classList.add(
        'active'
    );

    if (heartSnackbarTimer) {
        clearTimeout(
            heartSnackbarTimer
        );
    }

    heartSnackbarTimer = setTimeout(
        () => {
            snackbar.classList.remove(
                'active'
            );
        },
        4000
    );
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
        window.heartMomentText
            .feelings[feeling]
        || feeling
        || ''
    );
}


function formatMomentDate(value) {
    if (!value) {
        return '';
    }

    const date = new Date(
        `${value}T00:00:00`
    );

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return value;
    }

    return date.toLocaleDateString();
}


function heartMomentProfilePictureUrl(author) {
    const filename =
        author
        && author.profilePicture
            ? author.profilePicture
            : 'profile-placeholder.jpg';

    return (
        '/api/v2/media/static/'
        + encodeURIComponent(filename)
    );
}


function heartMomentImageUrl(moment) {
    const version = encodeURIComponent(
        moment.dateModified
        || moment.dateCreated
        || ''
    );

    return (
        `/api/v2/heart-moments/`
        + `${encodeURIComponent(moment.id)}`
        + `/image?v=${version}`
    );
}


function revokeObjectUrl(url) {
    if (url) {
        URL.revokeObjectURL(url);
    }
}


function previewCreateHeartImage() {
    const input = document.getElementById(
        'heart-create-image'
    );

    const preview = document.getElementById(
        'heart-create-image-preview'
    );

    const wrap = document.getElementById(
        'heart-create-image-preview-wrap'
    );

    const remove = document.getElementById(
        'heart-create-remove-image'
    );

    const file = input.files[0];

    if (!file) {
        clearCreateHeartImage();
        return;
    }

    revokeObjectUrl(
        createImageObjectUrl
    );

    createImageObjectUrl =
        URL.createObjectURL(file);

    preview.src =
        createImageObjectUrl;

    wrap.style.display = '';
    remove.style.display = '';
}


function clearCreateHeartImage() {
    const input = document.getElementById(
        'heart-create-image'
    );

    const preview = document.getElementById(
        'heart-create-image-preview'
    );

    const wrap = document.getElementById(
        'heart-create-image-preview-wrap'
    );

    const remove = document.getElementById(
        'heart-create-remove-image'
    );

    input.value = '';

    preview.removeAttribute('src');

    wrap.style.display = 'none';
    remove.style.display = 'none';

    revokeObjectUrl(
        createImageObjectUrl
    );

    createImageObjectUrl = null;
}


function previewEditHeartImage() {
    const input = document.getElementById(
        'heart-edit-image'
    );

    const preview = document.getElementById(
        'heart-edit-image-preview'
    );

    const wrap = document.getElementById(
        'heart-edit-image-preview-wrap'
    );

    const remove = document.getElementById(
        'heart-edit-remove-image'
    );

    const file = input.files[0];

    if (!file) {
        return;
    }

    revokeObjectUrl(
        editImageObjectUrl
    );

    editImageObjectUrl =
        URL.createObjectURL(file);

    preview.src =
        editImageObjectUrl;

    wrap.style.display = '';
    remove.style.display = '';

    editRemoveImage = false;
}


function clearEditHeartImage() {
    const input = document.getElementById(
        'heart-edit-image'
    );

    const preview = document.getElementById(
        'heart-edit-image-preview'
    );

    const wrap = document.getElementById(
        'heart-edit-image-preview-wrap'
    );

    const remove = document.getElementById(
        'heart-edit-remove-image'
    );

    input.value = '';

    preview.removeAttribute('src');

    wrap.style.display = 'none';
    remove.style.display = 'none';

    revokeObjectUrl(
        editImageObjectUrl
    );

    editImageObjectUrl = null;

    editRemoveImage = true;
}


async function uploadHeartMomentImage(
    id,
    file
) {
    const formData = new FormData();

    formData.append(
        'image',
        file
    );

    const response = await fetch(
        `/api/v2/heart-moments/${encodeURIComponent(id)}/image`,
        {
            method: 'POST',
            body: formData
        }
    );

    const result = await response.json();

    if (
        !response.ok
        || result.status !== 'success'
    ) {
        throw new Error(
            result.message
            || window.heartMomentText
                .imageUploadError
        );
    }

    return result.data.item;
}


async function removeHeartMomentImage(
    id
) {
    const response = await fetch(
        `/api/v2/heart-moments/${encodeURIComponent(id)}/image`,
        {
            method: 'DELETE'
        }
    );

    const result = await response.json();

    if (
        !response.ok
        || result.status !== 'success'
    ) {
        throw new Error(
            result.message
            || window.heartMomentText
                .imageRemoveError
        );
    }

    return result.data.item;
}


function setHeartMomentFilter(
    filter,
    button
) {
    currentHeartMomentFilter = filter;

    document
        .querySelectorAll(
            '.heart-filter'
        )
        .forEach(
            element => {
                element.classList.remove(
                    'fill'
                );
            }
        );

    if (button) {
        button.classList.add(
            'fill'
        );
    }

    loadHeartMoments();
}


async function loadHeartMoments() {
    const loading =
        document.getElementById(
            'heart-moments-loading'
        );

    const empty =
        document.getElementById(
            'heart-moments-empty'
        );

    const list =
        document.getElementById(
            'heart-moments-list'
        );

    loading.style.display = '';
    empty.style.display = 'none';

    list.innerHTML = '';

    try {
        const response = await fetch(
            `/api/v2/heart-moments?filter=${encodeURIComponent(currentHeartMomentFilter)}`
        );

        const result =
            await response.json();

        if (
            !response.ok
            || result.status !== 'success'
        ) {
            throw new Error(
                result.message
                || window.heartMomentText
                    .loadError
            );
        }

        currentHeartMoments =
            result.data.items || [];

        renderHeartMoments();

        if (heartMomentHighlightId) {
            const target =
                document.getElementById(
                    `heart-moment-${heartMomentHighlightId}`
                );

            if (target) {
                window.setTimeout(
                    () => {
                        target.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center'
                        });
                    },
                    100
                );
            }
        }

    } catch (error) {
        console.error(
            '[HeartMoments] Load failed:',
            error
        );

        showHeartSnackbar(
            window.heartMomentText
                .loadError,
            true
        );

    } finally {
        loading.style.display =
            'none';
    }
}


function formatMomentDateDashboard(value) {
    if (!value) {
        return '';
    }

    const datePart =
        String(value)
            .slice(0, 10);

    const parts =
        datePart.split('-');

    if (parts.length !== 3) {
        return formatMomentDate(value);
    }

    const year =
        parts[0].slice(-2);

    const month =
        parts[1].padStart(2, '0');

    const day =
        parts[2].padStart(2, '0');

    return `${day}.${month}.${year}`;
}


function renderHeartMoments() {
    const list =
        document.getElementById(
            'heart-moments-list'
        );

    const empty =
        document.getElementById(
            'heart-moments-empty'
        );

    list.innerHTML = '';

    if (
        !currentHeartMoments.length
    ) {
        empty.style.display = '';
        return;
    }

    empty.style.display = 'none';

    currentHeartMoments.forEach(
        moment => {
            list.appendChild(
                createHeartMomentCard(
                    moment
                )
            );
        }
    );
}


function createHeartMomentCard(
    moment
) {
    const article =
        document.createElement(
            'article'
        );

    article.className =
        'surface-container no-padding '
        + 'heart-moment-card';

    article.id =
        `heart-moment-${moment.id}`;

    if (
        heartMomentHighlightId
        && Number(heartMomentHighlightId)
            === Number(moment.id)
    ) {
        article.classList.add(
            'heart-moment-highlight'
        );
    }

    const header =
        document.createElement('div');

    header.className = 'row';

    const feelingIconElement =
        document.createElement('i');

    feelingIconElement.className =
        'circle';

    feelingIconElement.textContent =
        feelingIcon(
            moment.feeling
        );

    const titleArea =
        document.createElement('div');

    titleArea.className = 'max';

    const feelingTitle =
        document.createElement('h6');

    feelingTitle.className = 'small';

    feelingTitle.textContent =
        feelingLabel(
            moment.feeling
        );

    const meta =
        document.createElement('div');

    meta.className =
        'heart-moment-meta small-text';

    const dateElement =
        document.createElement('a');

    dateElement.className =
        'heart-moment-date-chip '
        + 'chip no-border secondary small round';

    dateElement.textContent =
        formatMomentDateDashboard(
            moment.momentDate
        );

    meta.appendChild(
        dateElement
    );

    if (moment.author) {
        const authorElement =
            document.createElement(
                'span'
            );

        authorElement.className =
            'heart-moment-author';

        const authorName = [
            moment.author.firstName,
            moment.author.lastName
        ]
            .filter(Boolean)
            .join(' ');

        const avatar =
            document.createElement(
                'img'
            );

        avatar.className =
            'circle heart-moment-author-avatar';

        const usesPlaceholder =
            !moment.author.profilePicture
            || moment.author.profilePicture
                === 'profile-placeholder.jpg';

        if (!usesPlaceholder) {
            avatar.classList.add(
                'heart-moment-author-avatar-custom'
            );
        }

        avatar.alt = '';
        avatar.loading = 'lazy';

        avatar.src =
            heartMomentProfilePictureUrl(
                moment.author
            );

        avatar.addEventListener(
            'error',
            () => {
                if (
                    !avatar.src.endsWith(
                        '/api/v2/media/static/profile-placeholder.jpg'
                    )
                ) {
                    avatar.src =
                        '/api/v2/media/static/profile-placeholder.jpg';
                }
            }
        );

        authorElement.appendChild(
            avatar
        );

        const authorNameElement =
            document.createElement(
                'span'
            );

        authorNameElement.textContent =
            authorName;

        authorElement.appendChild(
            authorNameElement
        );

        meta.appendChild(
            authorElement
        );
    }

    const visibilityElement =
        document.createElement('span');

    visibilityElement.className =
        'heart-moment-visibility';

    visibilityElement.textContent =
        moment.visibility === 'private'
            ? `🔒 ${window.heartMomentText.private}`
            : `♡ ${window.heartMomentText.shared}`;

    meta.appendChild(
        visibilityElement
    );

    titleArea.appendChild(
        feelingTitle
    );

    titleArea.appendChild(
        meta
    );

    header.appendChild(
        feelingIconElement
    );

    header.appendChild(
        titleArea
    );

    const ownMoment =
        Number(moment.authorUserID)
        === Number(
            window.currentHeartMomentUserId
        );

    if (ownMoment) {
        const actions =
            document.createElement('div');

        actions.className =
            'heart-moment-actions';

        const editButton =
            document.createElement(
                'button'
            );

        editButton.className =
            'circle transparent';

        editButton.type = 'button';

        const editIcon =
            document.createElement('i');

        editIcon.textContent = 'edit';

        editButton.appendChild(
            editIcon
        );

        editButton.addEventListener(
            'click',
            () => {
                openEditHeartMoment(
                    moment.id
                );
            }
        );

        const deleteButton =
            document.createElement(
                'button'
            );

        deleteButton.className =
            'circle transparent';

        deleteButton.type = 'button';

        const deleteIcon =
            document.createElement('i');

        deleteIcon.textContent =
            'delete';

        deleteButton.appendChild(
            deleteIcon
        );

        deleteButton.addEventListener(
            'click',
            () => {
                deleteHeartMoment(
                    moment.id
                );
            }
        );

        actions.appendChild(
            editButton
        );

        actions.appendChild(
            deleteButton
        );

        header.appendChild(
            actions
        );
    }

    article.appendChild(
        header
    );

    const description =
        document.createElement('p');

    description.className =
        'heart-moment-description';

    description.textContent =
        moment.description || '';

    article.appendChild(
        description
    );

    if (moment.mediaFilename) {
        const image =
            document.createElement('img');

        image.className =
            'heart-moment-image';

        image.loading = 'lazy';

        image.alt =
            moment.description || '';

        image.src =
            heartMomentImageUrl(
                moment
            );

        article.appendChild(
            image
        );
    }

    /*
     * Meta-Daten aus dem Header lösen und als
     * Dashboard-artigen Footer ans Kartenende setzen.
     */
    meta.classList.add(
        'heart-moment-footer'
    );

    article.appendChild(meta);

    return article;
}


function openCreateHeartMoment() {
    document.getElementById(
        'heart-create-date'
    ).value = localDateISO();

    document.getElementById(
        'heart-create-description'
    ).value = '';

    document.getElementById(
        'heart-create-feeling'
    ).value = 'seen';

    document.getElementById(
        'heart-create-visibility'
    ).value = 'shared';

    clearCreateHeartImage();

    callUi(
        '#dialog-create-heart-moment'
    );
}


async function saveHeartMoment() {
    const description =
        document
            .getElementById(
                'heart-create-description'
            )
            .value
            .trim();

    if (!description) {
        showHeartSnackbar(
            window.heartMomentText
                .descriptionRequired,
            true
        );

        return;
    }

    const payload = {
        momentDate:
            document.getElementById(
                'heart-create-date'
            ).value,

        description,

        feeling:
            document.getElementById(
                'heart-create-feeling'
            ).value,

        visibility:
            document.getElementById(
                'heart-create-visibility'
            ).value
    };

    const imageInput =
        document.getElementById(
            'heart-create-image'
        );

    const imageFile =
        imageInput.files[0] || null;

    try {
        const response = await fetch(
            '/api/v2/heart-moments',
            {
                method: 'POST',

                headers: {
                    'Content-Type':
                        'application/json'
                },

                body: JSON.stringify(
                    payload
                )
            }
        );

        const result =
            await response.json();

        if (
            !response.ok
            || result.status !== 'success'
        ) {
            throw new Error(
                result.message
                || window.heartMomentText
                    .saveError
            );
        }

        const moment =
            result.data.item;

        if (imageFile) {
            try {
                await uploadHeartMomentImage(
                    moment.id,
                    imageFile
                );

            } catch (imageError) {
                console.error(
                    '[HeartMoments] '
                    + 'Image upload failed:',
                    imageError
                );

                callUi(
                    '#dialog-create-heart-moment'
                );

                showHeartSnackbar(
                    window.heartMomentText
                        .imageUploadError,
                    true
                );

                await loadHeartMoments();

                return;
            }
        }

        callUi(
            '#dialog-create-heart-moment'
        );

        showHeartSnackbar(
            window.heartMomentText
                .created
        );

        await loadHeartMoments();

    } catch (error) {
        console.error(
            '[HeartMoments] '
            + 'Create failed:',
            error
        );

        showHeartSnackbar(
            error.message
            || window.heartMomentText
                .saveError,
            true
        );
    }
}


function openEditHeartMoment(id) {
    const moment =
        currentHeartMoments.find(
            item =>
                Number(item.id)
                === Number(id)
        );

    if (!moment) {
        return;
    }

    document.getElementById(
        'heart-edit-id'
    ).value = moment.id;

    document.getElementById(
        'heart-edit-date'
    ).value =
        moment.momentDate || '';

    document.getElementById(
        'heart-edit-description'
    ).value =
        moment.description || '';

    document.getElementById(
        'heart-edit-feeling'
    ).value =
        moment.feeling;

    document.getElementById(
        'heart-edit-visibility'
    ).value =
        moment.visibility;

    const input =
        document.getElementById(
            'heart-edit-image'
        );

    const preview =
        document.getElementById(
            'heart-edit-image-preview'
        );

    const wrap =
        document.getElementById(
            'heart-edit-image-preview-wrap'
        );

    const remove =
        document.getElementById(
            'heart-edit-remove-image'
        );

    input.value = '';

    revokeObjectUrl(
        editImageObjectUrl
    );

    editImageObjectUrl = null;
    editRemoveImage = false;

    if (moment.mediaFilename) {
        preview.src =
            heartMomentImageUrl(
                moment
            );

        wrap.style.display = '';
        remove.style.display = '';

    } else {
        preview.removeAttribute('src');

        wrap.style.display = 'none';
        remove.style.display = 'none';
    }

    callUi(
        '#dialog-edit-heart-moment'
    );
}


async function saveEditedHeartMoment() {
    const id =
        document.getElementById(
            'heart-edit-id'
        ).value;

    const description =
        document
            .getElementById(
                'heart-edit-description'
            )
            .value
            .trim();

    if (!description) {
        showHeartSnackbar(
            window.heartMomentText
                .descriptionRequired,
            true
        );

        return;
    }

    const payload = {
        momentDate:
            document.getElementById(
                'heart-edit-date'
            ).value,

        description,

        feeling:
            document.getElementById(
                'heart-edit-feeling'
            ).value,

        visibility:
            document.getElementById(
                'heart-edit-visibility'
            ).value
    };

    const imageInput =
        document.getElementById(
            'heart-edit-image'
        );

    const newImage =
        imageInput.files[0] || null;

    try {
        const response = await fetch(
            `/api/v2/heart-moments/${encodeURIComponent(id)}`,
            {
                method: 'PUT',

                headers: {
                    'Content-Type':
                        'application/json'
                },

                body: JSON.stringify(
                    payload
                )
            }
        );

        const result =
            await response.json();

        if (
            !response.ok
            || result.status !== 'success'
        ) {
            throw new Error(
                result.message
                || window.heartMomentText
                    .saveError
            );
        }

        try {
            if (newImage) {
                await uploadHeartMomentImage(
                    id,
                    newImage
                );

            } else if (
                editRemoveImage
            ) {
                await removeHeartMomentImage(
                    id
                );
            }

        } catch (imageError) {
            console.error(
                '[HeartMoments] '
                + 'Image update failed:',
                imageError
            );

            callUi(
                '#dialog-edit-heart-moment'
            );

            showHeartSnackbar(
                newImage
                    ? window.heartMomentText
                        .imageUploadError
                    : window.heartMomentText
                        .imageRemoveError,
                true
            );

            await loadHeartMoments();

            return;
        }

        callUi(
            '#dialog-edit-heart-moment'
        );

        showHeartSnackbar(
            window.heartMomentText
                .updated
        );

        await loadHeartMoments();

    } catch (error) {
        console.error(
            '[HeartMoments] '
            + 'Update failed:',
            error
        );

        showHeartSnackbar(
            error.message
            || window.heartMomentText
                .saveError,
            true
        );
    }
}


async function deleteHeartMoment(id) {
    if (
        !window.confirm(
            window.heartMomentText
                .deleteConfirm
        )
    ) {
        return;
    }

    try {
        const response = await fetch(
            `/api/v2/heart-moments/${encodeURIComponent(id)}`,
            {
                method: 'DELETE'
            }
        );

        const result =
            await response.json();

        if (
            !response.ok
            || result.status !== 'success'
        ) {
            throw new Error(
                result.message
                || window.heartMomentText
                    .deleteError
            );
        }

        showHeartSnackbar(
            window.heartMomentText
                .deleted
        );

        await loadHeartMoments();

    } catch (error) {
        console.error(
            '[HeartMoments] '
            + 'Delete failed:',
            error
        );

        showHeartSnackbar(
            error.message
            || window.heartMomentText
                .deleteError,
            true
        );
    }
}


document.addEventListener(
    'DOMContentLoaded',
    () => {
        const createDate =
            document.getElementById(
                'heart-create-date'
            );

        if (createDate) {
            createDate.value =
                localDateISO();
        }

        loadHeartMoments();
    }
);
