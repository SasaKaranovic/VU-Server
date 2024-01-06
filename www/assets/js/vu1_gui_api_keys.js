
// When page is loaded
$(function() {
  // Handler for .ready() called.
    gui_update_api_key_ui();
    triggerTooltipGen();
    triggerPopoverGen();

    $("#nav-api").addClass("active");
    gui_update_modal_available_dials();
    triggerModalGen();

    $("#modal-select-all").click(function(){
        gui_modal_select_all_dials(true);
    });

    $("#modal-deselect-all").click(function(){
        gui_modal_select_all_dials(false);
    });

    $("#modal-add-new-key").click(function(){
        gui_handle_modal_submit();
    });

});

function gui_handle_modal_submit()
{
    var dial_list = [];

    // Get Key name
    const key_name = $('#modal-new-key-name').val();
    if (key_name.length === 0)
    {
        $('#modal-new-key-name').addClass('is-invalid');
        return;
    }
    else
    {
        $('#modal-new-key-name').removeClass('is-invalid');
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

    var url = '/api/v0/admin/keys/create?admin_key='+ API_MASTER_KEY +'&name='+ key_name +'&dials='+ dial_access_str;
    var jqxhr = $.post(url, function() {
    })
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


function gui_modal_select_all_dials(checked)
{
    $('#modal-dials-list input:checkbox').each(function(){ this.checked = checked; });
}

function gui_update_modal_available_dials()
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


function gui_update_dial_name(name)
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/name?name='+ name +'&key='+ API_MASTER_KEY );
    $('#dial-title').text('Name: '+ name);
    $('#dial-name').text(name);
}


function gui_update_api_key_ui()
{
    const api_keys = vu1_get_api_keys(false);

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
