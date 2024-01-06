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


function create_toast(toast_title, toast_message)
{
    var toast = '\
                    <div class="toast show" role="alert" aria-live="assertive" aria-atomic="true" data-bs-autohide="false" data-bs-toggle="toast">\
                    <div class="toast-header">\
                    <strong class="me-auto">'+ toast_title +'</strong>\
                    <button type="button" class="ms-2 btn-close" data-bs-dismiss="toast" aria-label="Close"></button>\
                    </div>\
                    <div class="toast-body">\
                    '+ toast_message +'\
                    </div>\
                    </div>';
    $("#content").append(toast);
}


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

function triggerModalGen()
{
    // console.log("triggerModalGen");

    // $('*[data-bs-toggle="modal"]').on('click', function(event) {
    //     console.log('Click!');
    //     console.log(this);
    // });

    // EventHandler.on(document, EVENT_CLICK_DATA_API$2, SELECTOR_DATA_TOGGLE$2, function (event) {
    //   const target = SelectorEngine.getElementFromSelector(this);
    //   if (['A', 'AREA'].includes(this.tagName)) {
    //     event.preventDefault();
    //   }
    //   EventHandler.one(target, EVENT_SHOW$4, showEvent => {
    //     if (showEvent.defaultPrevented) {
    //       return;
    //     }
    //     EventHandler.one(target, EVENT_HIDDEN$4, () => {
    //       if (isVisible(this)) {
    //         this.focus();
    //       }
    //     });
    //   });
    //   const alreadyOpen = SelectorEngine.findOne(OPEN_SELECTOR$1);
    //   if (alreadyOpen) {
    //     Modal.getInstance(alreadyOpen).hide();
    //   }
    //   const data = Modal.getOrCreateInstance(target);
    //   data.toggle(this);
    // });
}
