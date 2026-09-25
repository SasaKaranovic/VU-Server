// Web UI shell: routes ?page= to a view and holds helpers the views share.

// Must match server.master_key in config.yaml, or every Web UI request is rejected.
const API_MASTER_KEY = 'cTpAWYuRpA2zx75Yh961Cg';
const urlParams = new URLSearchParams(window.location.search);
const PAGES = ['dial', 'api_keys', 'key_settings'];

$(function () {
    // make_version.py stamps the version into footer.html, so it stays a separate view.
    $("#pagefooter").load("views/footer.html");

    const page = urlParams.get('page');
    $("#content").load("views/" + (PAGES.includes(page) ? page : 'start') + ".html");
});


/** Create tooltips and popovers for elements added after Tabler's own init. */
function initBsWidgets()
{
    const widgets = {tooltip: bootstrap.Tooltip, popover: bootstrap.Popover};
    for (const [toggle, Widget] of Object.entries(widgets))
    {
        document.querySelectorAll('[data-bs-toggle="' + toggle + '"]').forEach(function (el) {
            Widget.getOrCreateInstance(el, {
                delay: {show: 50, hide: 50},
                html: el.getAttribute('data-bs-html') === 'true',
                placement: el.getAttribute('data-bs-placement') ?? 'auto',
            });
        });
    }
}


/** Fill #modal-dials-list with one checkbox per dial and wire the select all and none buttons. */
async function gui_render_dial_picker()
{
    const dials = await vu1_get_dial_list();

    $('#modal-dials-list').text("");
    $.each(dials, function (key, val) {
        const dial_name = (val['dial_name'] == 'Not set') ? val['uid'] : val['dial_name'];
        $('#modal-dials-list').append('\
            <label class="form-selectgroup-item">\
              <input type="checkbox" name="modal-dial-checkbox" value="'+ val['uid'] +'" class="form-selectgroup-input" />\
              <span class="form-selectgroup-label">'+ dial_name +'</span>\
            </label>\
        ');
    });

    $("#modal-select-all").click(function () { gui_select_all_dials(true); });
    $("#modal-deselect-all").click(function () { gui_select_all_dials(false); });
}

function gui_select_all_dials(checked)
{
    $('#modal-dials-list input:checkbox').prop('checked', checked);
}


/**
 * Validate a key form and flag its first invalid field.
 * @param {string} name_input selector of the key name input
 * @returns {{name: string, dials: string}|null} the name and ";"-joined dial UIDs, or null when invalid.
 */
function gui_read_key_form(name_input)
{
    const name = $(name_input).val();
    $(name_input).toggleClass('is-invalid', name.length === 0);
    if (name.length === 0)
    {
        return null;
    }

    const dials = $('#modal-dials-list input:checkbox:checked').map(function () { return this.value; }).get();
    $('#modal-select-header').toggleClass('alert alert-warning', dials.length < 1);
    if (dials.length < 1)
    {
        return null;
    }

    return {name: name, dials: dials.join(";")};
}
