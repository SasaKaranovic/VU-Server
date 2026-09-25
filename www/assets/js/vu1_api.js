// Read-only VU-Server API calls shared by the Web UI views.

/** GET an API path and return the response's `data`, or [] when the request fails. */
async function api_request(url)
{
    try {
        const response = await fetch("/api/v0/" + url);
        const result = await response.json();
        return (result['status'] == 'ok' && result['data']) || [];
    } catch (e) {
        return [];
    }
}

/** @returns {Promise<Object[]>} every dial the server knows. */
function vu1_get_dial_list()
{
    return api_request('dial/list?key=' + API_MASTER_KEY);
}

/** @returns {Promise<Object|Array>} one dial's status, or [] when it is missing. */
function vu1_get_dial_info(uid)
{
    return api_request('dial/' + uid + '/status?key=' + API_MASTER_KEY);
}

/** @returns {Promise<Object[]>} every API key. */
function vu1_get_api_keys()
{
    return api_request('admin/keys/list?admin_key=' + API_MASTER_KEY);
}
