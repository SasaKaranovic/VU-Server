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


# Want to contribute?

As mentioned, right now, VU Dials adoption is the main hurdle for everyone enjoying VU dials in combination with their favourite game/applications/service.

For developers interested in supporting VU dials natively or through extension/addon/plugin, please take a look at [VU Dials API](https://docs.vudials.com/api_messaging/) documentation to learn how you can communicate with the dials through VU server.

For non-developers interested in supporting VU dials; you can reach out to your favorite developers and let them know that you would appreciate if they could integrate VU dials in their software.

We could use any and all the love that the community has to offer. :)


---

[VU Dials Home page](https://vudials.com)



