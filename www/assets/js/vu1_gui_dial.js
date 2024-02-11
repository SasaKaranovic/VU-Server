
// When page is loaded
$(function() {
  // Handler for .ready() called.
    gui_update_dial_ui();

    // re-trigger
    triggerTooltipGen();
    triggerPopoverGen();
});


$("#btn-change-name").on( "click", function() {
    const new_name = $("#new-dial-name").val();

    if (
        (new_name != undefined) &&
        (new_name !== "") &&
        (new_name.length >= 3) &&
        (new_name.length <= 30)
        )
    {
        $("#new-dial-name").removeClass("is-invalid");
        $("#dial-name-rules").hide();
        gui_update_dial_name(new_name);
    }
    else
    {
        $("#dial-name-rules").show();
        $("#new-dial-name").removeClass("is-valid");
        $("#new-dial-name").addClass("is-invalid");
    }
} );

// Identify buttons
$(".vu1-identify-button").on( "click", function() {
    const r = $(this).data('sk-red');
    const g = $(this).data('sk-green');
    const b = $(this).data('sk-blue');
    const v = $(this).data('sk-value');

    gui_update_dial_backlight(r,g,b);
    gui_update_dial_value(v);
});

// Behaviour buttons
$(".vu1-behaviour-button").on( "click", function() {
    const dial_period = $(this).data('sk-dial-period');
    const dial_step = $(this).data('sk-dial-step');
    const bl_period = $(this).data('sk-backlight-period');
    const bl_step = $(this).data('sk-backlight-step');

    gui_set_dial_easing(dial_period, dial_step);
    gui_set_backlight_easing(bl_period, bl_step);
});


//Dial info buttons
$("#dial-reload-info").on( "click", function() {
    $("#dial-reload-container").html('<span class="status status-indigo"><span class="status-dot status-dot-animated"></span>Loading...</span>');
    gui_reload_dial_info();
});



function gui_set_dial_easing(period, step)
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/easing/dial?step='+ step +'&period='+ period +'&key='+ API_MASTER_KEY )
    .done(function( data ) {
        window.location.reload(true);
    });
}

function gui_set_backlight_easing(period, step)
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/easing/backlight?step='+ step +'&period='+ period +'&key='+ API_MASTER_KEY )
    .done(function( data ) {
        window.location.reload(true);
    });
}

function gui_reload_dial_info()
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/reload?key='+ API_MASTER_KEY )
    .done(function( data ) {
        window.location.reload(true);
    });
}

function gui_update_dial_backlight(r, g, b)
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/backlight?red='+ r +'&green='+ g +'&blue='+ b +'&key='+ API_MASTER_KEY );
}

function gui_update_dial_value(v)
{
    const dial_uid = $.urlParam('uid');
    $.get( '/api/v0/dial/' + dial_uid  + '/set?value='+ v +'&key='+ API_MASTER_KEY );
}

function gui_update_dial_name(name)
{
    const dial_uid = $.urlParam('uid');

    $.ajax({
      url  : '/api/v0/dial/' + dial_uid  + '/name?name='+ name +'&key='+ API_MASTER_KEY,
      type : 'GET',
    })
    .done(function(data, statusText, xhr){
      var status = xhr.status;                //200
        if (status == 201)
        {
            $('#dial-title').text('Name: '+ name);
            $('#dial-name').text(name);
            $("#dial-server-issue").hide();
            $("#new-dial-name").addClass("is-valid");
        }
    })
    .fail(function(data, statusText, xhr){
        $("#dial-server-issue-message").text(statusText + ': '+ data['responseJSON']['message']);
        $("#dial-server-issue").show();
    });

    // $.get( '/api/v0/dial/' + dial_uid  + '/name?name='+ name +'&key='+ API_MASTER_KEY );

}

function gui_update_dial_ui()
{
    const dial_uid = $.urlParam('uid');

    $.when( vu1_get_dial_info(dial_uid)  ).then(function(dial_info) {
        if (Array.isArray(dial_info) == false || !('uid' in dial_info))
        {
            console.log("No dial information. Using default values");
            // Dial does not exist. Create dummy dial data
            var easing = [];
            easing['dial_step'] = "??";
            easing['dial_period'] = "??";
            easing['backlight_step'] = "??";
            easing['backlight_period'] = "??";

            dial_info['dial_name'] = "Unknown (Invalid/Missing dial?)";
            dial_info['uid'] = "NO-UID";
            dial_info['fw_version'] = "??";
            dial_info['fw_hash'] = "??";
            dial_info['hw_version'] = "??";
            dial_info['protocol_version'] = "??";
            dial_info['easing'] = easing;
            var dial_type = '?unknown?';
        }
        else
        {
            var dial_type = (dial_info['index'] == 0) ? 'HUB+Dial' : 'Dial';
        }


        $('#dial-title').text('Name: '+ dial_info['dial_name']);
        $('#dial-name').text(dial_info['dial_name']);
        $('#dial-uid').text(dial_info['uid']);
        $('#dial-type').text(dial_type);
        $('#dial-fw-version').text(dial_info['fw_version']);
        $('#dial-fw-build').text(dial_info['fw_hash']);
        $('#dial-hw-version').text(dial_info['hw_version']);
        $('#dial-protocol-version').text(dial_info['protocol_version']);
        $('#dial-easing-step').text(dial_info['easing']['dial_step']);
        $('#dial-easing-period').text(dial_info['easing']['dial_period']);
        $('#backlight-easing-step').text(dial_info['easing']['backlight_step']);
        $('#backlight-easing-period').text(dial_info['easing']['backlight_period']);
        $("#dial-background-img").attr("src","/api/v0/dial/"+dial_uid+"/image/get");

    });
}


