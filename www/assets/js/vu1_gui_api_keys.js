// API keys view: key table and the create-key modal.

$(function() {
    gui_update_api_key_ui();
    gui_render_dial_picker();
    initBsWidgets();

    $("#nav-api").addClass("active");

    $("#modal-add-new-key").click(function(){
        gui_handle_modal_submit();
    });
});

function gui_handle_modal_submit()
{
    const form = gui_read_key_form('#modal-new-key-name');
    if (form === null)
    {
        return;
    }

    var url = '/api/v0/admin/keys/create?admin_key='+ API_MASTER_KEY +'&name='+ form.name +'&dials='+ form.dials;
    $.post(url)
      .done(function(e) {
        const status = e['status'];
        if (status == 'ok')
        {
            location.reload();
        }
        else
        {
            alert('Failed to create API key');
        }

      });
}


async function gui_update_api_key_ui()
{
    const api_keys = await vu1_get_api_keys();

    $.each( api_keys, function( key, val ) {
        $('#table_api_keys').append('<tr>\
        <td></td>\
        <td><span class="text-secondary">'+ val['key_name'] + '</span></td>\
        <td><p class="user-select-all"><kbd>'+ val['key_uid'] + '</kbd></p</td>\
        <td class="text-end">\
        <span class="dropdown">\
        <a href="index.html?page=key_settings&key_id='+ val['key_uid'] +'" class="btn" role="button">Settings</a>\
        </span>\
        </td>\
        </tr>\
        ');

    });
}
