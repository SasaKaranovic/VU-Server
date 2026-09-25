// Key settings view: edit or delete one API key's name and dial access.

$(function() {
    gui_update_key_settings_ui();
    initBsWidgets();

    $("#nav-api").addClass("active");

    $("#submit-update-key").click(function(){
        gui_handle_submit();
    });

    $("#btn-delete-key").click(function(){
        gui_handle_key_delete();
    });
});


async function gui_update_key_settings_ui()
{
    // The key's dials are ticked in the picker, so the picker must exist first.
    await gui_render_dial_picker();

    const available_api_keys = await vu1_get_api_keys();
    const target_key = urlParams.get('key_id');
    const key_info = available_api_keys.find(val => val['key_uid'] == target_key);

    if (key_info === undefined)
    {
        return;
    }

    // Remove delete for master key
    if (key_info['priviledges'] >= 99)
    {
        $( "#btn-delete-key" ).remove();
        $( "#submit-update-key" ).remove();
        $('#submit-cancel-key').text("Back");
        $('#modal-dials-list').text("Master API key has access to all dials");
    }

    // Update titles
    $('.vu1-key-name').text(key_info['key_name']);
    $('input.vu1-key-name').val(key_info['key_name']);

    // Select dials
    $.each( key_info['dials'], function( key, val ) {
        $('input:checkbox[value="' + val + '"]').prop('checked', true);
    });
}

function gui_handle_key_delete()
{
    const key_uid = urlParams.get('key_id');

    $.get( "/api/v0/admin/keys/remove?admin_key=" + API_MASTER_KEY +"&key="+key_uid)
      .done(function( e ) {
        const status = e['status'];
        if (status == 'ok')
        {
            window.location.replace("/index.html?page=api_keys");
        }
        else
        {
            alert('Failed to update API key. ' + e['message']);

        }
      });
}


function gui_handle_submit()
{
    const form = gui_read_key_form('#input-key-name');
    if (form === null)
    {
        return;
    }

    var post_data = { 'admin_key': API_MASTER_KEY, 'key': urlParams.get('key_id'), 'name': form.name, 'dials': form.dials}

    $.post( "/api/v0/admin/keys/update", post_data)
      .done(function( e ) {
        const status = e['status'];
        if (status == 'ok')
        {
            window.location.replace("/index.html?page=api_keys");
        }
        else
        {
            alert('Failed to update API key');
        }
      });
}
