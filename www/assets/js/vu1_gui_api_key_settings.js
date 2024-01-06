// When page is loaded
$(function() {
  // Handler for .ready() called.
    gui_update_available_dials();
    gui_update_api_key_ui();

    triggerTooltipGen();
    triggerPopoverGen();

    $("#nav-api").addClass("active");

    $("#modal-select-all").click(function(){
        gui_select_all_dials(true);
    });

    $("#modal-deselect-all").click(function(){
        gui_select_all_dials(false);
    });

    $("#submit-update-key").click(function(){
        gui_handle_submit();
    });

    $("#btn-delete-key").click(function(){
        gui_handle_key_delete();
    });
});


function gui_select_all_dials(checked)
{
    $('#modal-dials-list input:checkbox').each(function(){ this.checked = checked; });
}

function gui_update_available_dials()
{
    const available_dials = vu1_get_dial_list(false);

    $('#modal-dials-list').text("");

    $.each( available_dials, function( key, val ) {
        let dial_name = val['dial_name'];
        if (dial_name == 'Not set')
        {
            dial_name = val['uid'];
        }

        $('#modal-dials-list').append('\
            <label class="form-selectgroup-item">\
              <input type="checkbox" name="modal-dial-checkbox" value="'+ val['uid'] +'" class="form-selectgroup-input" />\
              <span class="form-selectgroup-label">'+ dial_name +'</span>\
            </label>\
        ');

    });
}


function gui_update_api_key_ui()
{
    const available_api_keys = vu1_get_api_keys(false);
    const target_key = $.urlParam('key_id')
    key_info = false;

    $.each( available_api_keys, function( key, val ) {
        if (val['key_uid'] == target_key) {
            key_info = val;
        }
    });

    if (key_info === false)
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
    const key_uid = $.urlParam('key_id');

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
    const key_uid = $.urlParam('key_id');
    var dial_list = [];

    // Get Key name
    const name = $('#input-key-name').val();
    if (name.length === 0)
    {
        $('#input-key-name').addClass('is-invalid');
        return;
    }
    else
    {
        $('#input-key-name').removeClass('is-invalid');
    }

    // Get all selected dials
    $('#modal-dials-list input:checkbox').each(function(){
        if (this.checked)
        {
            dial_list.push(this.value);
        }
     });

    if (dial_list.length < 1 )
    {
        $('#modal-select-header').addClass('alert alert-warning ');
        return;
    }
    else
    {
        $('#modal-select-header').removeClass('alert alert-warning ');
    }


    const dial_access_str = dial_list.join(";");

    var post_data = { 'admin_key': API_MASTER_KEY, 'key': key_uid, 'name':name, 'dials': dial_access_str}

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
