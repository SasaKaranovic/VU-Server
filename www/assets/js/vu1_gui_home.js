
// When page is loaded
$(function() {
    // Handler for .ready() called.
    gui_update_dial_ui();
    gui_update_api_ui();

    $("#nav-home").addClass("active");
});

$("#btn-search-for-dials").on( "click", function() {
    gui_search_for_dials();
} );

$("#btn-reset-all-dials").on( "click", function() {
    gui_reset_all_dials();
} );

function gui_update_dial_ui()
{
    const dials = vu1_get_dial_list(false);

    $.each( dials, function( key, val ) {
        $('#table_dials').append('<tr>\
        <td><span class="text-secondary">'+ val['uid'] + '</span></td>\
        <td>'+ val['dial_name'] + '</td>\
        <td class="text-end">\
        <span class="dropdown">\
        <a href="index.html?page=dial&uid='+ val['uid'] +'" class="btn" role="button">Settings</a>\
        </span>\
        </td>\
        </tr>\
        ');

    });

    $('#card-dial-count').text(dials.length + ' Online')
}

function gui_update_api_ui()
{
    const api_keys = vu1_get_api_keys();
    $('#card-api-count').text(Object.keys(api_keys).length + ' API keys')
}


function gui_search_for_dials()
{
    $("#btn-search-for-dials").text("Searching... Please wait...");

    $.get( "/api/v0/dial/provision?admin_key=" + API_MASTER_KEY)
      .done(function( e ) {
        const status = e['status'];
        if (status == 'ok')
        {
            window.location.replace("/index.html");
        }
        else
        {
            alert('Failed to provision new dial. ' + e['message']);

        }
      });
}

function gui_reset_all_dials()
{
    if (!confirm("Reset ALL dials on the bus? Every dial will reboot and its "
                 + "value, backlight and image will be re-pushed."))
    {
        return;
    }

    const $btn = $("#btn-reset-all-dials");
    const original = $btn.text();
    $btn.text("Resetting... Please wait...");

    $.get( "/api/v0/dial/reset_all?admin_key=" + API_MASTER_KEY)
      .done(function( e ) {
        const status = e['status'];
        if (status == 'ok')
        {
            window.location.replace("/index.html");
        }
        else
        {
            alert('Failed to reset dials. ' + e['message']);
            $btn.text(original);
        }
      })
      .fail(function() {
        alert('Failed to reset dials. Request error.');
        $btn.text(original);
      });
}
