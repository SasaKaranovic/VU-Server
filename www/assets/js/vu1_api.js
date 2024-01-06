
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


function vu1_get_dial_list(return_dict=false)
{
    const dial_data = api_request('dial/list'+'?key='+ API_MASTER_KEY);
    var dials = [];

    if(return_dict)
    {
        for (const [key, value] of Object.entries(dial_data))
        {
            dials[value['uid']] = value;
        }
    }
    else
    {
        dials = dial_data;
    }

    return dials;
}

function vu1_get_dial_info(uid)
{
    return api_request('dial/'+ uid + '/status'+'?key='+ API_MASTER_KEY);
}


function vu1_get_api_keys(return_dict=false)
{
    const api_keys = api_request('admin/keys/list?admin_key='+ API_MASTER_KEY);
    var keys = [];

    if(return_dict)
    {
        for (const [key, value] of Object.entries(api_keys))
        {
            keys[value['uid']] = value;
        }
    }
    else
    {
        keys = api_keys;
    }

    return keys;
}
