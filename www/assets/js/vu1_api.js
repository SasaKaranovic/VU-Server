
function api_request(url)
{
    var items = [];

    jQuery.ajax({
        url: "/api/v0/" + url,
        success: function (result) {
            if (result['status'] == 'ok')
            {
                $.each( result['data'], function( key, val ) {
                    items[key] = val;
                });
            }
        },
        async: false,
        dataType: 'json'
    });

    return items;
}


function vu1_get_dial_list()
{
    return api_request('dial/list'+'?key='+ API_MASTER_KEY);
}

function vu1_get_dial_info(uid)
{
    return api_request('dial/'+ uid + '/status'+'?key='+ API_MASTER_KEY);
}


function vu1_get_api_keys()
{
    return api_request('admin/keys/list?admin_key='+ API_MASTER_KEY);
}
