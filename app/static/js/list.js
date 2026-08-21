function handleListItemClick(
    row,
    event,
    id
) {
    if (
        event.target.closest(
            '.list-delete-button'
        )
    ) {
        return;
    }

    /*
     * Native Checkbox-Umschaltung verhindern.
     * Wir steuern den Status selbst, damit Klick
     * auf Text, Zeile oder Checkbox identisch ist.
     */
    event.preventDefault();

    const checkbox =
        row.querySelector(
            'input[type="checkbox"]'
        );

    if (!checkbox) {
        return;
    }

    checkbox.checked =
        !checkbox.checked;

    updateListItem(
        id,
        checkbox.checked
    );
}


function updateListItem(
    id,
    value
) {
    if (!navigator.onLine) {
        revertCheckbox(
            id,
            value ? 1 : 0
        );

        showSnackbar(
            'list',
            true,
            'error',
            _('You are offline'),
            null,
            false
        );

        return;
    }


    const numericValue =
        value
            ? 1
            : 0;


    const formData =
        new FormData();

    formData.append(
        'content',
        numericValue
    );

    formData.append(
        'listType',
        window.listType
    );


    fetch(
        '/api/v2/item/' + id,
        {
            method: 'PUT',
            body: formData,
        }
    )
        .then(
            async response => {
                try {
                    const result =
                        await response.json();

                    if (
                        result.status
                        === 'success'
                    ) {
                        document
                            .getElementById(
                                'div-render-list-items'
                            )
                            .innerHTML =
                                result
                                    .data
                                    .rendered_items;

                        showSnackbar(
                            'list',
                            true,
                            'green',
                            result.message,
                            result,
                            false
                        );

                    } else {
                        if (
                            result.data
                            && result.data
                                .rendered_items
                        ) {
                            document
                                .getElementById(
                                    'div-render-list-items'
                                )
                                .innerHTML =
                                    result
                                        .data
                                        .rendered_items;

                        } else {
                            revertCheckbox(
                                id,
                                numericValue
                            );
                        }

                        showSnackbar(
                            'list',
                            true,
                            'error',
                            result.message,
                            result,
                            true
                        );
                    }

                } catch (error) {
                    revertCheckbox(
                        id,
                        numericValue
                    );

                    showSnackbar(
                        'list',
                        true,
                        'error',
                        _('Server not reachable'),
                        null,
                        false
                    );
                }
            }
        )
        .catch(
            error => {
                revertCheckbox(
                    id,
                    numericValue
                );

                if (
                    String(error)
                    === 'TypeError: Failed to fetch'
                ) {
                    error =
                        _('Server not reachable');
                }

                showSnackbar(
                    'list',
                    true,
                    'error',
                    error,
                    null,
                    false
                );
            }
        );
}


async function deleteListItem(
    id,
    button
) {
    if (!navigator.onLine) {
        showSnackbar(
            'list',
            true,
            'error',
            _('You are offline'),
            null,
            false
        );

        return;
    }


    if (
        !confirm(
            _('Delete selected items?')
        )
    ) {
        return;
    }


    const icon =
        button.querySelector('i');

    const oldIcon =
        icon
            ? icon.textContent
            : 'delete';


    button.disabled = true;

    if (icon) {
        icon.textContent =
            'hourglass_top';
    }


    const formData =
        new FormData();

    formData.append(
        'ids',
        id
    );

    formData.append(
        'listType',
        window.listType
    );


    try {
        const response =
            await fetch(
                '/api/v2/items',
                {
                    method: 'DELETE',
                    body: formData,
                }
            );


        const result =
            await response.json();


        if (
            result.status
            !== 'success'
        ) {
            throw result;
        }


        document
            .getElementById(
                'div-render-list-items'
            )
            .innerHTML =
                result
                    .data
                    .rendered_items;


        showSnackbar(
            'list',
            true,
            'green',
            result.message,
            result,
            false
        );


    } catch (error) {
        button.disabled = false;

        if (icon) {
            icon.textContent =
                oldIcon;
        }


        const message =
            error
            && error.message
                ? error.message
                : (
                    String(error)
                    === 'TypeError: Failed to fetch'
                        ? _('Server not reachable')
                        : String(error)
                );


        showSnackbar(
            'list',
            true,
            'error',
            message,
            error,
            true
        );
    }
}


function revertCheckbox(
    id,
    failedValue
) {
    const row =
        document.querySelector(
            '#div-render-list-items '
            + `.list-item-row[data-item-id="${id}"]`
        );

    if (!row) {
        return;
    }


    const checkbox =
        row.querySelector(
            'input[type="checkbox"]'
        );

    if (!checkbox) {
        return;
    }


    checkbox.checked =
        failedValue === 1
            ? false
            : true;
}
