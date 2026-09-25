// Dial settings view: shows one dial's details and sends identify, behaviour, name, reload and reset commands.

const dial_uid = urlParams.get('uid');

$(function() {
    gui_update_dial_ui();
    initBsWidgets();
});


/** GET a per-dial endpoint for this view's dial, adding the master key. */
function dialCall(op, params = {})
{
    const query = new URLSearchParams({...params, key: API_MASTER_KEY});
    return fetch('/api/v0/dial/' + dial_uid + '/' + op + '?' + query);
}


$("#btn-change-name").on( "click", async function() {
    const new_name = $("#new-dial-name").val();

    if (new_name.length < 3 || new_name.length > 30)
    {
        $("#dial-name-rules").show();
        $("#new-dial-name").removeClass("is-valid");
        $("#new-dial-name").addClass("is-invalid");
        return;
    }

    $("#new-dial-name").removeClass("is-invalid");
    $("#dial-name-rules").hide();

    const response = await dialCall('name', {name: new_name});
    if (response.status == 201)
    {
        $('#dial-title').text('Name: '+ new_name);
        $("#dial-server-issue").hide();
        $("#new-dial-name").addClass("is-valid");
    }
    else if (!response.ok)
    {
        const result = await response.json();
        $("#dial-server-issue-message").text('error: '+ result['message']);
        $("#dial-server-issue").show();
    }
} );

// Identify buttons
$(".vu1-identify-button").on( "click", function() {
    const b = $(this).data();
    dialCall('backlight', {red: b.skRed, green: b.skGreen, blue: b.skBlue});
    dialCall('set', {value: b.skValue});
});

// Behaviour buttons
$(".vu1-behaviour-button").on( "click", async function() {
    const b = $(this).data();
    const responses = await Promise.all([
        dialCall('easing/dial', {step: b.skDialStep, period: b.skDialPeriod}),
        dialCall('easing/backlight', {step: b.skBacklightStep, period: b.skBacklightPeriod}),
    ]);
    if (responses.some(r => r.ok))
    {
        window.location.reload();
    }
});


//Dial info buttons
$("#dial-reload-info").on( "click", async function() {
    $("#dial-reload-container").html('<span class="status status-indigo"><span class="status-dot status-dot-animated"></span>Loading...</span>');
    const response = await dialCall('reload');
    if (response.ok)
    {
        window.location.reload();
    }
});

$("#dial-reset-device").on( "click", async function() {
    if (!confirm("Reset this dial? Its cached backlight state is cleared and "
                 + "its value, colour and image are re-pushed."))
    {
        return;
    }
    $("#dial-reset-container").html('<span class="status status-red"><span class="status-dot status-dot-animated"></span>Resetting...</span>');
    const response = await dialCall('reset').catch(() => null);
    if (!response?.ok)
    {
        alert('Failed to reset dial. Request error.');
    }
    window.location.reload();
});


async function gui_update_dial_ui()
{
    const dial_info = await vu1_get_dial_info(dial_uid);
    if (!('uid' in dial_info))
    {
        $('#dial-title').text('Name: Unknown (Invalid/Missing dial?)');
        return;
    }

    $('#dial-title').text('Name: '+ dial_info['dial_name']);
    $('#dial-uid').text(dial_info['uid']);
    $('#dial-type').text((dial_info['index'] == 0) ? 'HUB+Dial' : 'Dial');
    $('#dial-fw-version').text(dial_info['fw_version']);
    $('#dial-fw-build').text(dial_info['fw_hash']);
    $('#dial-hw-version').text(dial_info['hw_version']);
    $('#dial-protocol-version').text(dial_info['protocol_version']);
    $('#dial-easing-step').text(dial_info['easing']['dial_step']);
    $('#dial-easing-period').text(dial_info['easing']['dial_period']);
    $('#backlight-easing-step').text(dial_info['easing']['backlight_step']);
    $('#backlight-easing-period').text(dial_info['easing']['backlight_period']);
    $("#dial-background-img").attr("src","/api/v0/dial/"+dial_uid+"/image/get");
}
