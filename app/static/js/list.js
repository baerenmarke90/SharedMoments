let listSelectionMode = false;

const selectedListItems =
    new Set();


function handleListRowClick(
    event,
    row,
    id
) {
    /*
     * Buttons und Checkboxen verwalten
     * ihre Aktion selbst.
     */
    if (
        event.target.closest(
            'button, input, label, a'
        )
    ) {
        return;
    }


    /*
     * Auswahlmodus:
     * Klick auf die Zeile markiert den
     * Eintrag zum gemeinsamen Löschen.
     */
    if (listSelectionMode) {
        toggleListItemSelection(
            id
        );

        return;
    }


    /*
     * Normalmodus:
     * Klick auf die Zeile schaltet
     * offen <-> erledigt.
     */
    const checkbox =
        row.querySelector(
            '.list-status-control '
            + 'input[type="checkbox"]'
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
            value
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


    const formData =
        new FormData();

    formData.append(
        'content',
        value ? 1 : 0
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

                    return;
                }


                revertCheckbox(
                    id,
                    value
                );

                showSnackbar(
                    'list',
                    true,
                    'error',
                    result.message,
                    result,
                    true
                );
            }
        )
        .catch(
            error => {
                revertCheckbox(
                    id,
                    value
                );

                showSnackbar(
                    'list',
                    true,
                    'error',
                    String(error)
                        === 'TypeError: Failed to fetch'
                            ? _('Server not reachable')
                            : String(error),
                    null,
                    false
                );
            }
        );
}


function revertCheckbox(
    id,
    attemptedValue
) {
    const row =
        document.querySelector(
            '.list-item-row'
            + `[data-item-id="${id}"]`
        );

    if (!row) {
        return;
    }


    const checkbox =
        row.querySelector(
            '.list-status-control '
            + 'input[type="checkbox"]'
        );

    if (!checkbox) {
        return;
    }


    checkbox.checked =
        !attemptedValue;
}


/* =========================================================
 * MEHRFACH-AUSWAHL
 * ========================================================= */


function startListSelectionMode() {
    listSelectionMode = true;

    selectedListItems.clear();


    document.body.classList.add(
        'list-selection-active'
    );


    const footer =
        document.getElementById(
            'footer-list-selection'
        );

    if (footer) {
        footer.style.display = '';
    }


    const createFab =
        document.getElementById(
            'div-fab-create-new-list-entry'
        );

    if (createFab) {
        createFab.style.display =
            'none';
    }


    syncListSelectionUi();
}


function exitListSelectionMode() {
    listSelectionMode = false;

    selectedListItems.clear();


    document.body.classList.remove(
        'list-selection-active'
    );


    document
        .querySelectorAll(
            '.list-item-row'
        )
        .forEach(
            row => {
                row.classList.remove(
                    'list-item-selected'
                );

                const checkbox =
                    row.querySelector(
                        '.list-select-checkbox'
                    );

                if (checkbox) {
                    checkbox.checked =
                        false;
                }
            }
        );


    const footer =
        document.getElementById(
            'footer-list-selection'
        );

    if (footer) {
        footer.style.display =
            'none';
    }


    const createFab =
        document.getElementById(
            'div-fab-create-new-list-entry'
        );

    if (createFab) {
        createFab.style.display =
            '';
    }


    syncListSelectionUi();
}


function toggleListItemSelection(
    id
) {
    id = String(id);

    if (
        selectedListItems.has(id)
    ) {
        selectedListItems.delete(id);

    } else {
        selectedListItems.add(id);
    }


    syncListSelectionUi();
}


function setListItemSelected(
    id,
    selected
) {
    id = String(id);

    if (selected) {
        selectedListItems.add(id);

    } else {
        selectedListItems.delete(id);
    }


    syncListSelectionUi();
}


function syncListSelectionUi() {
    document
        .querySelectorAll(
            '.list-item-row'
        )
        .forEach(
            row => {
                const id =
                    String(
                        row.dataset.itemId
                    );

                const selected =
                    selectedListItems.has(
                        id
                    );


                row.classList.toggle(
                    'list-item-selected',
                    selected
                );


                const checkbox =
                    row.querySelector(
                        '.list-select-checkbox'
                    );

                if (checkbox) {
                    checkbox.checked =
                        selected;
                }
            }
        );


    const count =
        document.getElementById(
            'list-selection-count'
        );

    if (count) {
        count.textContent =
            selectedListItems.size;
    }


    const deleteButton =
        document.getElementById(
            'list-selection-delete-button'
        );

    if (deleteButton) {
        deleteButton.disabled =
            selectedListItems.size === 0;
    }
}


function toggleSelectAllListItems() {
    const rows =
        Array.from(
            document.querySelectorAll(
                '.list-item-row'
            )
        );


    const allSelected =
        rows.length > 0
        && selectedListItems.size
            === rows.length;


    selectedListItems.clear();


    if (!allSelected) {
        rows.forEach(
            row => {
                selectedListItems.add(
                    String(
                        row.dataset.itemId
                    )
                );
            }
        );
    }


    syncListSelectionUi();
}


/* =========================================================
 * LÖSCHEN
 * ========================================================= */


function deleteSingleListItem(
    id,
    button
) {
    deleteListItems(
        [String(id)],
        button
    );
}


function deleteSelectedListItems(
    button
) {
    const ids =
        Array.from(
            selectedListItems
        );


    if (!ids.length) {
        return;
    }


    deleteListItems(
        ids,
        button
    );
}


async function deleteListItems(
    ids,
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


    /*
     * Vor JEDEM Löschen bestätigen.
     *
     * Vorhandene SharedMoments-
     * Übersetzung wird verwendet.
     */
    if (
        !confirm(
            _('Delete selected items?')
        )
    ) {
        return;
    }


    const icon =
        button
            ? button.querySelector('i')
            : null;

    const originalIcon =
        icon
            ? icon.textContent
            : null;


    if (button) {
        button.disabled = true;
    }

    if (icon) {
        icon.textContent =
            'hourglass_top';
    }


    const formData =
        new FormData();

    formData.append(
        'ids',
        ids.join(',')
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


        exitListSelectionMode();


        showSnackbar(
            'list',
            true,
            'green',
            result.message,
            result,
            false
        );


    } catch (error) {
        if (button) {
            button.disabled =
                false;
        }

        if (
            icon
            && originalIcon
        ) {
            icon.textContent =
                originalIcon;
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
