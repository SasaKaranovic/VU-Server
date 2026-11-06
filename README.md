# VU Dials - VU Server


![VU1 Dial](assets/vu1_hello_world.png?raw=true "VU1 Dial")

This is the official VU dials repository for the VU Server application and it's source code.

You can learn more about VU dials at [VUDials.com](https://vudials.com)

The VU Server is a key component of the VU dials.

It provides a Web API that can be interfaced by any third party application/script/service, allowing it to easily interact with and control the VU dials.

For example, in order to update a dial, any application can make a simple [API request](https://docs.vudials.com/api/dial_UID_set/) to the VU server and that's it.


# Demo application

Right now, we have a very simple [VU1 demo application](https://github.com/SasaKaranovic/VU-Demo-App) that runs on Windows and demonstrates how dials can be used for resource usage monitoring.

You can download it from [VUDials Download page](https://vudials.com/download/demo_app) (or look at the [source code](https://github.com/SasaKaranovic/VU-Demo-App)).

Demo application uses VU Server API to demonstrate how a third party application can interact with VU dials.


# Why not build apps for VU dials?

You might ask why build an API server? Why not just build more stand-alone applications for VU dials? It's not that simple, but we believe that we have a good reason for this decision...

VU dials can display virtually any information, and we all have our favourite/preferred applications for temperature monitoring, CPU/GPU/MEM load monitoring, weather app, stock monitoring, and the list can go on for days.

If we started building new applications specifically for VU dials, we would be forcing our users to choose between their existing favourite application and the new one that works with VU dials.

In the long run, this would result in "splitting the community" or forcing users to choose between abandoning perfectly fine software packages or abandoning the option to show some information on the VU dials.

Instead, our approach is that we have completely opened the VU dials to the community and any third-party application/script/service running on your PC (or even network).

Any application can make a straightforward API request to the VU server and say, "Hey, update dial X to show the value of Y", and that's it.

Making a web API request is a very simple thing to do in almost any software package.

So how does this benefit the community?

This approach should allow existing applications to integrate/support VU dials natively or through extensions/addons/plugins. This means you still get to use your favourite application, but as a bonus, it now works seamlessly with VU dials.

We are aware of the big caveat, which is that VU dial adoption won't happen over night and that it will require a lot of love and support from the community and developers.

But we strongly believe that in the long run this is a much better approach than creating another closed-source, black-box product that forces you to use prescribed app store if you want to use the product.



# How to run/install VU Server

For Windows we have an installer that can be download from [https://vudials.com/download/server](https://vudials.com/download/server)

For Linux and Mac users, we don't have the installer (yet), but you can run the VU Server from the source code.

We have a simple example that describes how to run VU Server from source code on a Linux machine.


[Jump to Linux Running From Source Code read me](Running_from_source_on_linux.md)


# Watching dial state

`GET /api/v0/dial/events?key=<api key>` streams the dials your key can access as Server-Sent Events. Use it to see changes made by other clients and whether each change has reached the dial. Writes still go through the REST API.

```bash
curl -N "http://localhost:5340/api/v0/dial/events?key=cTpAWYuRpA2zx75Yh961Cg"
```

`-N` stops curl from buffering. Each `dials` event carries the full list for your key, in the same shape as `/api/v0/dial/list` plus three fields:

```
event: dials
data: {"dials":[{"uid":"3E0075000650564139323920","dial_name":"CPU","value":60,"backlight":{"red":0,"green":50,"blue":100},"image_file":"/opt/VU-Server/upload/img_3E0075000650564139323920","image_rev":0,"value_delivery":"pending","backlight_delivery":"delivered"}]}
```

Replace your state with each event instead of merging it. A dial that disappears was unplugged or your key lost access to it. The server checks for changes once per `dial_update_period`, so a burst of writes arrives as one event with the latest values. Every connection starts with a `dials` event, even when the list is empty, and there are no event ids to resume from.

`value_delivery` and `backlight_delivery` read `delivered` once the hub acknowledged the current value, `pending` while it is queued, `retrying` after a failed attempt and `unresponsive` once the server gave up. Send the value again to retry an unresponsive dial. A write delivered within one check can go straight to `delivered`.

`image_rev` changes whenever a new image is uploaded, so fetch `/api/v0/dial/<uid>/image/get` when it does. It restarts at 0 with the server, so fetch every image again whenever the stream reconnects.

A missing or unknown key gets a `401` JSON response. If the key is deleted, the stream sends `event: key_revoked` and ends. Lines starting with `:` are keepalives sent after 15 seconds without an event.

In a browser, use `EventSource` and `addEventListener`, because named events do not reach `onmessage`. Open one stream per page, since browsers allow about six connections per server.

```js
const events = new EventSource(`http://localhost:5340/api/v0/dial/events?key=${key}`);
events.addEventListener('dials', (e) => render(JSON.parse(e.data).dials));
events.addEventListener('key_revoked', () => events.close());
```


# Want to contribute?

As mentioned, right now, VU Dials adoption is the main hurdle for everyone enjoying VU dials in combination with their favourite game/applications/service.

For developers interested in supporting VU dials natively or through extension/addon/plugin, please take a look at [VU Dials API](https://docs.vudials.com/api_messaging/) documentation to learn how you can communicate with the dials through VU server.

For non-developers interested in supporting VU dials; you can reach out to your favorite developers and let them know that you would appreciate if they could integrate VU dials in their software.

We could use any and all the love that the community has to offer. :)


---

[VU Dials Home page](https://vudials.com)



