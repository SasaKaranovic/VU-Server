const API_MASTER_KEY = 'cTpAWYuRpA2zx75Yh961Cg';


$.urlParam = function(name){
    var results = new RegExp('[\?&]' + name + '=([^&#]*)').exec(window.location.href);
    if (results==null) {
       return null;
    }
    return decodeURI(results[1]) || 0;
}

// When page is loaded
$(function () {

    // Handle dynamic includes
    var includes = $('[data-include]')
    $.each(includes, function () {
        var file = 'views/' + $(this).data('include') + '.html'
        $(this).load(file)
    })

    // Check requested page
    if($.urlParam('page') == 'dial')
    {
        $("#content").load("views/dial.html");
    }
    else if($.urlParam('page') == 'api_keys')
    {
        $("#content").load("views/api_keys.html");
    }
    else if($.urlParam('page') == 'key_settings')
    {
        $("#content").load("views/key_settings.html");
    }
    else
    {
        $("#content").load("views/start.html");
    }

})


function triggerTooltipGen()
{
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
      var _ref, _tooltipTriggerEl$get;
      var options = {
        delay: {
          show: 50,
          hide: 50
        },
        html: (_ref = tooltipTriggerEl.getAttribute("data-bs-html") === "true") !== null && _ref !== void 0 ? _ref : false,
        placement: (_tooltipTriggerEl$get = tooltipTriggerEl.getAttribute('data-bs-placement')) !== null && _tooltipTriggerEl$get !== void 0 ? _tooltipTriggerEl$get : 'auto'
      };
      return new $.fn['tooltip'].Constructor(tooltipTriggerEl, options);
    });
}


function triggerPopoverGen()
{
    var popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
      var _ref, _popoverTriggerEl$get;
      var options = {
        delay: {
          show: 50,
          hide: 50
        },
        html: (_ref = popoverTriggerEl.getAttribute('data-bs-html') === "true") !== null && _ref !== void 0 ? _ref : false,
        placement: (_popoverTriggerEl$get = popoverTriggerEl.getAttribute('data-bs-placement')) !== null && _popoverTriggerEl$get !== void 0 ? _popoverTriggerEl$get : 'auto'
      };
      return new $.fn['popover'].Constructor(popoverTriggerEl, options);
    });
}
