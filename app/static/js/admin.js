// --- Tab Switching ---
function showAdminTab(tab) {
    const tabs = ['users', 'roles', 'shares', 'auth', 'features'];
    tabs.forEach(name => {
        const panel = document.getElementById('tab-' + name);
        const button = document.getElementById('tab-' + name + '-btn');
        if (panel) panel.style.display = name === tab ? '' : 'none';
        if (button) button.classList.toggle('active', name === tab);
    });

    const userFab = document.getElementById('fab-create-user');
    const roleFab = document.getElementById('fab-create-role');
    if (userFab) userFab.style.display = tab === 'users' ? '' : 'none';
    if (roleFab) roleFab.style.display = tab === 'roles' ? '' : 'none';
}

// --- Optional app features ---
async function setAdminFeature(input) {
    const enabled = Boolean(input.checked);
    const featureKey = input.dataset.featureKey;
    if (!featureKey) return;

    input.disabled = true;
    try {
        const response = await fetch(
            '/api/v2/admin/features/' + encodeURIComponent(featureKey),
            {
                method: 'PUT',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ enabled })
            }
        );
        const result = await response.json();
        if (!response.ok || result.status !== 'success') {
            throw new Error(
                result.message || 'Einstellung konnte nicht gespeichert werden.'
            );
        }
        showAdminSnackbar(result.message, false);
    } catch (error) {
        input.checked = !enabled;
        showAdminSnackbar(error.message || _('Server not reachable'), true);
    } finally {
        input.disabled = false;
    }
}

// --- User Create / Edit ---
function openCreateUser() {
    document.getElementById('edit-user-id').value = '';
    document.getElementById('edit-user-firstName').value = '';
    document.getElementById('edit-user-lastName').value = '';
    document.getElementById('edit-user-email').value = '';
    document.getElementById('edit-user-birthDate').value = '';
    document.getElementById('edit-user-password').value = '';
    document.getElementById('edit-user-passwordConfirm').value = '';
    document.getElementById('edit-user-password-label').textContent = _('Password');
    document.getElementById('edit-user-password-confirm-field').style.display = '';
    document.getElementById('edit-user-profilePicture').value = '';
    document.getElementById('edit-user-profilePicture-preview').style.display = 'none';
    document.getElementById('edit-user-title').textContent = _('Create user');
    document.getElementById('btn-delete-user').style.display = 'none';

    // Roles: default Adult checked
    renderRoleCheckboxes('edit-user-roles-checkboxes', [3]);
    hideAdminUserSystemSettings();

    callUi('#dialog-edit-user');
}

function editUser(userId, firstName, lastName, email, birthDate, profilePicture) {
    document.getElementById('edit-user-id').value = userId;
    document.getElementById('edit-user-firstName').value = firstName;
    document.getElementById('edit-user-lastName').value = lastName;
    document.getElementById('edit-user-email').value = email;
    document.getElementById('edit-user-birthDate').value = birthDate;
    document.getElementById('edit-user-password').value = '';
    document.getElementById('edit-user-passwordConfirm').value = '';
    document.getElementById('edit-user-password-label').textContent = _('New password (leave empty to keep)');
    document.getElementById('edit-user-password-confirm-field').style.display = '';
    document.getElementById('edit-user-profilePicture').value = '';
    const preview = document.getElementById('edit-user-profilePicture-preview');
    if (profilePicture) {
        preview.src = '/api/v2/media/static/' + profilePicture;
        preview.style.display = '';
    } else {
        preview.style.display = 'none';
    }
    document.getElementById('edit-user-title').textContent = _('Edit user');
    document.getElementById('btn-delete-user').style.display = '';

    // Roles
    const currentRoles = userRolesMap[userId] || [];
    renderRoleCheckboxes('edit-user-roles-checkboxes', currentRoles);
    renderAdminUserSystemSettings(userId);

    callUi('#dialog-edit-user');
}

function hideAdminUserSystemSettings() {
    const section = document.getElementById('edit-user-system-settings-section');
    const list = document.getElementById('edit-user-system-settings-list');
    if (section) section.style.display = 'none';
    if (list) list.innerHTML = '';
}

function renderAdminUserSystemSettings(userId) {
    const section = document.getElementById('edit-user-system-settings-section');
    const list = document.getElementById('edit-user-system-settings-list');
    if (!section || !list) return;

    const values = adminUserSystemSettings[String(userId)] || [];
    list.innerHTML = '';

    if (!values.length) {
        section.style.display = 'none';
        return;
    }

    values.forEach(item => {
        const row = document.createElement('div');
        row.style.padding = '0.45rem 0';
        row.style.borderBottom = '1px solid var(--outline-variant)';

        const key = document.createElement('div');
        key.style.fontSize = '0.78rem';
        key.style.fontWeight = '650';
        key.style.wordBreak = 'break-all';
        key.textContent = item.name;

        const value = document.createElement('div');
        value.style.marginTop = '0.1rem';
        value.style.fontSize = '0.82rem';
        value.style.opacity = '0.72';
        value.style.wordBreak = 'break-word';
        value.textContent = item.value || '—';

        row.appendChild(key);
        row.appendChild(value);
        list.appendChild(row);
    });

    const last = list.lastElementChild;
    if (last) last.style.borderBottom = '0';

    section.style.display = '';
}

function renderRoleCheckboxes(containerId, selectedRoleIds) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    allRoles.forEach(roleId => {
        // Die Rolle "Child" gehoert zur frueheren Family-Edition.
        if (allRoleNames[roleId] === 'Child') return;
        const checked = selectedRoleIds.includes(roleId) ? 'checked' : '';
        container.innerHTML += `
            <label class="checkbox" style="display: inline-block; margin: 4px 12px 4px 0;">
                <input type="checkbox" value="${roleId}" ${checked}>
                <span>${_(allRoleNames[roleId])}</span>
            </label>
        `;
    });
}

function previewUserImage(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('edit-user-profilePicture-preview');
            preview.src = e.target.result;
            preview.style.display = '';
        };
        reader.readAsDataURL(input.files[0]);
    }
}

function saveUser(btn) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    const userId = document.getElementById('edit-user-id').value;
    const isEdit = !!userId;

    const firstName = document.getElementById('edit-user-firstName').value.trim();
    const lastName = document.getElementById('edit-user-lastName').value.trim();
    const email = document.getElementById('edit-user-email').value.trim();
    const birthDate = document.getElementById('edit-user-birthDate').value;
    const password = document.getElementById('edit-user-password').value;
    const passwordConfirm = document.getElementById('edit-user-passwordConfirm').value;
    const profilePicFile = document.getElementById('edit-user-profilePicture').files[0];

    if (!firstName || !email) {
        showAdminSnackbar(_('First name and e-mail are required'), true);
        return;
    }
    if (!isEdit && !password) {
        showAdminSnackbar(_('Password is required'), true);
        return;
    }
    if (password && password !== passwordConfirm) {
        showAdminSnackbar(_('Passwords do not match.'), true);
        return;
    }

    // Get selected roles
    const roleCheckboxes = document.querySelectorAll('#edit-user-roles-checkboxes input[type="checkbox"]:checked');
    const roleIds = Array.from(roleCheckboxes).map(cb => parseInt(cb.value));
    if (roleIds.length === 0) {
        showAdminSnackbar(_('User must have at least one role'), true);
        return;
    }

    btnLoading(btn);

    const formData = new FormData();
    formData.append('firstName', firstName);
    formData.append('lastName', lastName);
    formData.append('email', email);
    if (birthDate) formData.append('birthDate', birthDate);
    if (password) formData.append('password', password);
    if (profilePicFile) formData.append('profilePicture', profilePicFile);
    if (!isEdit) formData.append('roleId', roleIds[0]); // Primary role for creation

    const url = isEdit ? `/api/v2/admin/users/${userId}` : '/api/v2/admin/users';
    const method = isEdit ? 'PUT' : 'POST';

    fetch(url, { method, body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                // If editing, also update roles
                const targetUserId = isEdit ? userId : result.data.id;
                const rolesFormData = new FormData();
                rolesFormData.append('roleIds', JSON.stringify(roleIds));

                return fetch(`/api/v2/admin/users/${targetUserId}/roles`, {
                    method: 'PUT',
                    body: rolesFormData
                }).then(r => r.json()).then(rolesResult => {
                    btnReset(btn);
                    callUi('#dialog-edit-user');
                    showAdminSnackbar(result.message, false);
                    location.reload();
                });
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error saving user:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

function deleteUser() {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    const userId = document.getElementById('edit-user-id').value;
    if (!userId) return;

    if (!confirm(_('Do you really want to delete this entry? All associated entries will also be deleted.'))) {
        return;
    }

    const btn = document.getElementById('btn-delete-user');
    btnLoading(btn);

    fetch(`/api/v2/admin/users/${userId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                btnReset(btn);
                callUi('#dialog-edit-user');
                showAdminSnackbar(result.message, false);
                location.reload();
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error deleting user:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

// --- User Roles (standalone dialog, kept for backwards compat) ---
function editUserRoles(userId, userName) {
    document.getElementById('edit-user-roles-user-id').value = userId;
    document.getElementById('edit-user-roles-title').textContent = userName;

    const currentRoles = userRolesMap[userId] || [];
    renderRoleCheckboxes('edit-user-roles-only-checkboxes', currentRoles);

    callUi('#dialog-edit-user-roles');
}

function saveUserRoles(btn) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    const userId = document.getElementById('edit-user-roles-user-id').value;
    const checkboxes = document.querySelectorAll('#edit-user-roles-only-checkboxes input[type="checkbox"]:checked');
    const roleIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

    if (roleIds.length === 0) {
        showAdminSnackbar(_('User must have at least one role'), true);
        return;
    }

    btnLoading(btn);

    const formData = new FormData();
    formData.append('roleIds', JSON.stringify(roleIds));

    fetch(`/api/v2/admin/users/${userId}/roles`, { method: 'PUT', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                userRolesMap[userId] = roleIds;
                btnReset(btn);
                callUi('#dialog-edit-user-roles');
                showAdminSnackbar(result.message, false);
                location.reload();
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error saving user roles:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

// --- Role Permissions ---
function editRolePermissions(roleId, roleName) {
    document.getElementById('edit-role-permissions-role-id').value = roleId;
    document.getElementById('edit-role-permissions-title').textContent = _(roleName);

    const currentPerms = rolePermissionsMap[roleId] || [];
    const container = document.getElementById('edit-role-permissions-checkboxes');
    container.innerHTML = '';

    const actions = ['View', 'Create', 'Update', 'Delete'];
    const listPerms = {};
    const globalPerms = [];

    allPermissions.forEach(perm => {
        if (perm.listTypeID) {
            if (!listPerms[perm.listTypeID]) listPerms[perm.listTypeID] = {};
            const action = perm.name.split(' ', 1)[0];
            listPerms[perm.listTypeID][action] = perm;
        } else {
            globalPerms.push(perm);
        }
    });

    // --- One unified table ---
    const cols = ['View', 'Create', 'Update', 'Delete'];
    let html = `<table class="border permission-matrix" style="width: 100%;">`;
    html += `<thead><tr><th style="text-align: left;"></th>`;
    cols.forEach(c => { html += `<th style="text-align: center;">${_(c)}</th>`; });
    html += `</tr></thead><tbody>`;

    // Helper: find View/Read perm for same entity
    const findViewPerm = (perm) => {
        const entity = perm.name.split(' ').slice(1).join(' ');
        return allPermissions.find(p =>
            p.listTypeID === perm.listTypeID &&
            p.name.split(' ').slice(1).join(' ') === entity &&
            (p.name.split(' ', 1)[0] === 'View' || p.name.split(' ', 1)[0] === 'Read')
        );
    };

    // Helper for checkbox cell
    const cell = (perm) => {
        if (!perm) return '<td></td>';
        const checked = currentPerms.includes(perm.id) ? 'checked' : '';
        const action = perm.name.split(' ', 1)[0];
        const needsView = ['Create', 'Update', 'Delete'].includes(action);
        const viewPerm = needsView ? findViewPerm(perm) : null;
        const disabled = needsView && viewPerm && !currentPerms.includes(viewPerm.id) ? 'disabled' : '';
        return `<td style="text-align: center;">
            <label class="checkbox">
                <input type="checkbox" value="${perm.id}" ${checked} ${disabled}
                    onchange="togglePermission(${roleId}, ${perm.id}, this.checked)">
                <span></span>
            </label>
        </td>`;
    };

    // Section: Lists
    html += `<tr><td colspan="5" style="padding-top: 16px;"><strong>${_('Lists')}</strong></td></tr>`;
    const sortedIds = Object.keys(listPerms).sort((a, b) => {
        const nameA = listPerms[a].View ? listPerms[a].View.name.split(' ').slice(1).join(' ') : '';
        const nameB = listPerms[b].View ? listPerms[b].View.name.split(' ').slice(1).join(' ') : '';
        return nameA.localeCompare(nameB);
    });
    sortedIds.forEach(ltId => {
        const p = listPerms[ltId];
        const name = p.View ? p.View.name.split(' ').slice(1).join(' ')
            : (p.Create ? p.Create.name.split(' ').slice(1).join(' ') : '?');
        html += `<tr><td style="padding-left: 16px;">${_(name)}</td>`;
        cols.forEach(action => { html += cell(p[action]); });
        html += `</tr>`;
    });

    // Section: General (CRUD-based global perms)
    const crudGroups = {};
    const standalonePerms = [];
    globalPerms.forEach(perm => {
        const action = perm.name.split(' ', 1)[0];
        if (['Create', 'Read', 'Update', 'Delete'].includes(action)) {
            const entity = perm.name.split(' ').slice(1).join(' ');
            if (!crudGroups[entity]) crudGroups[entity] = {};
            crudGroups[entity][action] = perm;
        } else {
            standalonePerms.push(perm);
        }
    });

    if (Object.keys(crudGroups).length > 0) {
        html += `<tr><td colspan="5" style="padding-top: 16px;"><strong>${_('General')}</strong></td></tr>`;
        Object.keys(crudGroups).sort().forEach(entity => {
            const g = crudGroups[entity];
            html += `<tr><td style="padding-left: 16px;">${_(entity)}</td>`;
            // Map Read→View column position
            html += cell(g['View'] || g['Read']);
            html += cell(g['Create']);
            html += cell(g['Update']);
            html += cell(g['Delete']);
            html += `</tr>`;
        });
    }

    // Section: Special (standalone perms)
    if (standalonePerms.length > 0) {
        html += `<tr><td colspan="5" style="padding-top: 16px;"><strong>${_('Special')}</strong></td></tr>`;
        standalonePerms.sort((a, b) => a.name.localeCompare(b.name)).forEach(perm => {
            const checked = currentPerms.includes(perm.id) ? 'checked' : '';
            html += `<tr><td style="padding-left: 16px;">${_(perm.name)}</td>`;
            html += `<td colspan="4" style="text-align: center;">
                <label class="checkbox">
                    <input type="checkbox" value="${perm.id}" ${checked}
                        onchange="togglePermission(${roleId}, ${perm.id}, this.checked)">
                    <span></span>
                </label>
            </td></tr>`;
        });
    }

    html += `</tbody></table>`;
    container.innerHTML = html;

    callUi('#dialog-edit-role-permissions');
}

function togglePermission(roleId, permId, checked) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    const currentPerms = rolePermissionsMap[roleId] || [];

    // Find the toggled permission
    const perm = allPermissions.find(p => p.id === permId);
    if (perm) {
        const action = perm.name.split(' ', 1)[0];
        const entity = perm.name.split(' ').slice(1).join(' ');
        const siblings = allPermissions.filter(p =>
            p.listTypeID === perm.listTypeID &&
            p.name.split(' ').slice(1).join(' ') === entity
        );

        if (checked && (action === 'View' || action === 'Read')) {
            // Enabling View → enable CUD checkboxes
            siblings.forEach(p => {
                const a = p.name.split(' ', 1)[0];
                if (['Create', 'Update', 'Delete'].includes(a)) {
                    const cb = document.querySelector(`#edit-role-permissions-checkboxes input[value="${p.id}"]`);
                    if (cb) cb.disabled = false;
                }
            });
        } else if (!checked && (action === 'View' || action === 'Read')) {
            // Deactivating View/Read → uncheck + disable CUD
            siblings.forEach(p => {
                const a = p.name.split(' ', 1)[0];
                if (['Create', 'Update', 'Delete'].includes(a)) {
                    const cb = document.querySelector(`#edit-role-permissions-checkboxes input[value="${p.id}"]`);
                    if (cb) { cb.checked = false; cb.disabled = true; }
                }
            });
        }
    }

    // Collect all checked checkboxes as new permission set
    const allChecked = document.querySelectorAll('#edit-role-permissions-checkboxes input[type="checkbox"]:checked');
    const newPerms = Array.from(allChecked).map(cb => parseInt(cb.value));

    const formData = new FormData();
    formData.append('permissionIds', JSON.stringify(newPerms));

    fetch(`/api/v2/admin/roles/${roleId}/permissions`, { method: 'PUT', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                rolePermissionsMap[roleId] = newPerms;
            } else {
                showAdminSnackbar(result.message, true);
                editRolePermissions(roleId, document.getElementById('edit-role-permissions-title').textContent);
            }
        })
        .catch(error => {
            showAdminSnackbar(_('Server not reachable'), true);
            editRolePermissions(roleId, document.getElementById('edit-role-permissions-title').textContent);
        });
}

// --- Create / Delete Roles ---
function createRole(btn) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    const roleName = document.getElementById('create-role-name').value.trim();
    if (!roleName) {
        showAdminSnackbar(_('Role name is required'), true);
        return;
    }

    btnLoading(btn);

    const formData = new FormData();
    formData.append('roleName', roleName);

    fetch('/api/v2/admin/roles', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                btnReset(btn);
                callUi('#dialog-create-role');
                document.getElementById('create-role-name').value = '';
                showAdminSnackbar(result.message, false);
                location.reload();
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error creating role:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

function deleteRole(roleId, roleName, btn) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    if (!confirm(_('Do you really want to delete this entry? All associated entries will also be deleted.'))) {
        return;
    }

    btnLoading(btn);

    fetch(`/api/v2/admin/roles/${roleId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                btnReset(btn);
                showAdminSnackbar(result.message, false);
                location.reload();
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error deleting role:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

// --- Share Management ---
function revokeShareAdmin(shareId, btn) {
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    if (!confirm(_('Revoke this share link?'))) return;

    btnLoading(btn);

    fetch(`/api/v2/admin/shares/${shareId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'success') {
                btnReset(btn);
                const row = document.getElementById('share-row-' + shareId);
                if (row) row.remove();
                const sharesTab = document.getElementById('tab-shares');
                if (sharesTab && !sharesTab.querySelector('[id^="share-row-"]')) {
                    sharesTab.innerHTML = '<article class="medium middle-align center-align primary-container"><div>' +
                        '<i class="extra">link_off</i>' +
                        '<h5>' + _('No active shares') + '</h5>' +
                        '<p>' + _('Share links will appear here once created.') + '</p>' +
                        '</div></article>';
                }
                showAdminSnackbar(result.message, false);
            } else {
                btnReset(btn);
                showAdminSnackbar(result.message, true);
            }
        })
        .catch(error => {
            btnReset(btn);
            console.error('Error revoking share:', error);
            showAdminSnackbar(_('Server not reachable'), true);
        });
}

// --- Snackbar ---
function showAdminSnackbar(message, isError) {
    const snackbar = document.getElementById('admin-snackbar');
    const text = document.getElementById('admin-snackbar-text');
    text.textContent = message;
    if (isError) {
        snackbar.className = 'snackbar error active';
    } else {
        snackbar.className = 'snackbar active';
    }
    setTimeout(() => snackbar.classList.remove('active'), 4000);
}

// --- Authentication settings (admin) ---
async function saveAuthenticationSettingsAdmin(button) {
    const localInput = document.getElementById('auth-local-login-enabled');
    const passkeyInput = document.getElementById('auth-passkey-login-enabled');
    if (!localInput || !passkeyInput) return;

    if (button) button.disabled = true;
    try {
        const response = await fetch('/api/v2/auth/settings', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                local_login_enabled: localInput.checked,
                passkey_login_enabled: passkeyInput.checked
            })
        });
        const result = await response.json();
        if (!response.ok || result.status !== 'success') {
            showAdminSnackbar(result.message || _('Authentication settings could not be saved.'), true);
            return;
        }
        showAdminSnackbar(result.message, false);
    } catch (error) {
        showAdminSnackbar(String(error), true);
    } finally {
        if (button) button.disabled = false;
    }
}

async function unlinkPocketIdAdmin(button) {
    if (!confirm(_('Unlink Pocket ID from this account?'))) return;
    if (!navigator.onLine) {
        showAdminSnackbar(_('You are offline'), true);
        return;
    }
    if (button) button.disabled = true;
    try {
        const response = await fetch('/api/v2/user/oidc', {method: 'DELETE'});
        const result = await response.json();
        if (!response.ok || result.status !== 'success') {
            showAdminSnackbar(result.message || _('Pocket ID could not be unlinked.'), true);
            return;
        }
        showAdminSnackbar(result.message, false);
        window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
        showAdminSnackbar(String(error), true);
    } finally {
        if (button) button.disabled = false;
    }
}

// --- Daily Questions administration ---
let dailyQuestionsAdminCategories = [];

async function dailyQuestionsAdminRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Accept': 'application/json',
            ...(options.body ? {'Content-Type': 'application/json'} : {}),
            ...(options.headers || {})
        }
    });
    const result = await response.json();
    if (!response.ok || result.status !== 'success') {
        throw new Error(result.message || 'Die Fragenverwaltung konnte nicht ausgeführt werden.');
    }
    return result;
}

function dailyQuestionsSourceLabel(source) {
    if (source === 'builtin') return 'Standard';
    if (source === 'custom') return 'Von euch';
    if (source === 'admin') return 'Admin';
    return source || 'Unbekannt';
}

function fillDailyQuestionCategorySelect(select, selectedValue) {
    if (!select) return;
    select.replaceChildren();
    dailyQuestionsAdminCategories.forEach(category => {
        const option = document.createElement('option');
        option.value = category.key;
        option.textContent = category.label;
        option.selected = category.key === selectedValue;
        select.appendChild(option);
    });
}

function renderDailyQuestionsAdmin(items) {
    const container = document.getElementById('admin-dq-list');
    if (!container) return;
    container.replaceChildren();

    if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'surface-container-low padding round center-align';
        empty.textContent = 'Keine passenden Fragen gefunden.';
        container.appendChild(empty);
        return;
    }

    items.forEach(item => {
        const card = document.createElement('article');
        card.className = 'surface-container-low padding round';
        card.style.marginBottom = '.75rem';
        card.dataset.questionId = String(item.id);

        const top = document.createElement('div');
        top.className = 'row';
        top.style.gap = '.5rem';
        top.style.alignItems = 'center';
        top.style.flexWrap = 'wrap';

        const source = document.createElement('span');
        source.className = 'chip small round';
        source.textContent = dailyQuestionsSourceLabel(item.source);

        const usage = document.createElement('span');
        usage.className = 'chip small round';
        usage.textContent = `${item.usage_count || 0}× verwendet`;

        const key = document.createElement('span');
        key.className = 'small-text max';
        key.style.opacity = '.6';
        key.style.textAlign = 'right';
        key.textContent = item.seed_key || '';

        top.append(source, usage, key);

        const questionField = document.createElement('div');
        questionField.className = 'field label border extra';
        questionField.style.marginTop = '.75rem';
        questionField.style.marginBottom = '.75rem';
        const textarea = document.createElement('textarea');
        textarea.maxLength = 500;
        textarea.value = item.question || '';
        textarea.dataset.dqField = 'question';
        const qLabel = document.createElement('label');
        qLabel.textContent = 'Frage';
        questionField.append(textarea, qLabel);

        const lower = document.createElement('div');
        lower.className = 'row';
        lower.style.gap = '.75rem';
        lower.style.alignItems = 'center';
        lower.style.flexWrap = 'wrap';

        const categoryField = document.createElement('div');
        categoryField.className = 'field label border suffix max';
        categoryField.style.margin = '0';
        categoryField.style.minWidth = '220px';
        const categorySelect = document.createElement('select');
        categorySelect.dataset.dqField = 'category';
        fillDailyQuestionCategorySelect(categorySelect, item.category);
        const categoryLabel = document.createElement('label');
        categoryLabel.textContent = 'Kategorie';
        const suffix = document.createElement('i');
        suffix.textContent = 'arrow_drop_down';
        categoryField.append(categorySelect, categoryLabel, suffix);

        const activeLabel = document.createElement('label');
        activeLabel.className = 'checkbox';
        const active = document.createElement('input');
        active.type = 'checkbox';
        active.checked = Boolean(item.active);
        active.dataset.dqField = 'active';
        const activeText = document.createElement('span');
        activeText.textContent = 'Aktiv';
        activeLabel.append(active, activeText);

        const actions = document.createElement('div');
        actions.className = 'row';
        actions.style.gap = '.35rem';
        actions.style.marginLeft = 'auto';

        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'round';
        save.innerHTML = '<i>save</i><span>Speichern</span>';
        save.addEventListener('click', () => saveDailyQuestionAdmin(item.id, save));

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'round transparent';
        remove.innerHTML = item.source === 'builtin'
            ? '<i>visibility_off</i><span>Deaktivieren</span>'
            : '<i>delete</i><span>Entfernen</span>';
        remove.addEventListener('click', () => deleteDailyQuestionAdmin(item.id, remove));

        actions.append(save, remove);
        lower.append(categoryField, activeLabel, actions);
        card.append(top, questionField, lower);
        container.appendChild(card);
    });
}

async function loadDailyQuestionsAdmin() {
    const panel = document.getElementById('daily-questions-admin-panel');
    const container = document.getElementById('admin-dq-list');
    if (!panel || !container) return;

    const query = document.getElementById('admin-dq-search')?.value.trim() || '';
    const source = document.getElementById('admin-dq-source')?.value || 'all';
    container.innerHTML = '<div class="center-align padding"><progress class="circle"></progress></div>';

    try {
        const params = new URLSearchParams({q: query, source});
        const result = await dailyQuestionsAdminRequest(`/api/v2/admin/daily-questions?${params.toString()}`);
        const data = result.data || {};
        dailyQuestionsAdminCategories = data.categories || [];

        const timezone = document.getElementById('admin-dq-timezone');
        if (timezone && data.timezone) timezone.value = data.timezone;

        const counts = data.counts || {};
        const all = document.getElementById('admin-dq-count-all');
        const active = document.getElementById('admin-dq-count-active');
        const custom = document.getElementById('admin-dq-count-custom');
        if (all) all.textContent = String(counts.all ?? 0);
        if (active) active.textContent = String(counts.active ?? 0);
        if (custom) custom.textContent = String(counts.custom ?? 0);

        fillDailyQuestionCategorySelect(
            document.getElementById('admin-dq-new-category'),
            dailyQuestionsAdminCategories[0]?.key || ''
        );
        renderDailyQuestionsAdmin(data.items || []);
    } catch (error) {
        container.textContent = error.message || 'Fragen konnten nicht geladen werden.';
        showAdminSnackbar(error.message || 'Fragen konnten nicht geladen werden.', true);
    }
}

async function saveDailyQuestionsTimezone(button) {
    const input = document.getElementById('admin-dq-timezone');
    if (!input) return;
    const timezone = input.value.trim();
    if (!timezone) {
        showAdminSnackbar('Bitte gib eine Zeitzone an.', true);
        return;
    }
    if (button) button.disabled = true;
    try {
        const result = await dailyQuestionsAdminRequest('/api/v2/admin/daily-questions/timezone', {
            method: 'PUT',
            body: JSON.stringify({timezone})
        });
        input.value = result.data?.timezone || timezone;
        showAdminSnackbar(result.message, false);
    } catch (error) {
        showAdminSnackbar(error.message, true);
    } finally {
        if (button) button.disabled = false;
    }
}

async function createDailyQuestionAdmin(button) {
    const input = document.getElementById('admin-dq-new-question');
    const category = document.getElementById('admin-dq-new-category');
    if (!input || !category) return;
    const question = input.value.trim();
    if (!question) {
        showAdminSnackbar('Bitte gib eine Frage ein.', true);
        input.focus();
        return;
    }
    if (button) button.disabled = true;
    try {
        const result = await dailyQuestionsAdminRequest('/api/v2/admin/daily-questions', {
            method: 'POST',
            body: JSON.stringify({question, category: category.value})
        });
        input.value = '';
        showAdminSnackbar(result.message, false);
        await loadDailyQuestionsAdmin();
    } catch (error) {
        showAdminSnackbar(error.message, true);
    } finally {
        if (button) button.disabled = false;
    }
}

async function saveDailyQuestionAdmin(questionId, button) {
    const card = document.querySelector(`[data-question-id="${questionId}"]`);
    if (!card) return;
    const question = card.querySelector('[data-dq-field="question"]')?.value.trim() || '';
    const category = card.querySelector('[data-dq-field="category"]')?.value || '';
    const active = Boolean(card.querySelector('[data-dq-field="active"]')?.checked);
    if (!question) {
        showAdminSnackbar('Bitte gib eine Frage ein.', true);
        return;
    }
    if (button) button.disabled = true;
    try {
        const result = await dailyQuestionsAdminRequest(`/api/v2/admin/daily-questions/${questionId}`, {
            method: 'PUT',
            body: JSON.stringify({question, category, active})
        });
        showAdminSnackbar(result.message, false);
        await loadDailyQuestionsAdmin();
    } catch (error) {
        showAdminSnackbar(error.message, true);
    } finally {
        if (button) button.disabled = false;
    }
}

async function deleteDailyQuestionAdmin(questionId, button) {
    if (!confirm('Diese Frage wirklich entfernen bzw. deaktivieren? Bereits verwendete Fragen bleiben aus Gründen der Historie erhalten.')) return;
    if (button) button.disabled = true;
    try {
        const result = await dailyQuestionsAdminRequest(`/api/v2/admin/daily-questions/${questionId}`, {
            method: 'DELETE'
        });
        showAdminSnackbar(result.message, false);
        await loadDailyQuestionsAdmin();
    } catch (error) {
        showAdminSnackbar(error.message, true);
    } finally {
        if (button) button.disabled = false;
    }
}

function initDailyQuestionsAdmin() {
    const panel = document.getElementById('daily-questions-admin-panel');
    if (!panel) return;
    const search = document.getElementById('admin-dq-search');
    if (search) {
        search.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                loadDailyQuestionsAdmin();
            }
        });
    }
    loadDailyQuestionsAdmin();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDailyQuestionsAdmin, {once: true});
} else {
    initDailyQuestionsAdmin();
}
