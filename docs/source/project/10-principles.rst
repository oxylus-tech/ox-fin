Principles
==========

This project follows those principles:


**0. Follow good practices:**

Humanly: *respect people* .

Technically: analyze, methodology, testing. It takes time to make good engineering. Stay simple, don't try to do everything at once: it is better to have less but working features.


**1. Develop modern web applications:** offer reactive and user experience oriented interfaces.

Technically speaking, use a web full stack using for backend the power of Django. Client-side take profit of the amazingness of Vue and related tools.

Each application systematically provided with:

    - Backend-side: application configuration, API (client), serializers, application view, other backend specifics;
    - Client side: Vue based Vite project, models, API (client);

We must enlight here some frontiers as they may be blur:

    - When a part of the interface requires some logic, behavior, widgets they must be encapsulated client-side.
    - In order to allow extensibility over templates rendering there still might be an equivalent as django's template.
    - Translation handling is kept under the respective owner of the text (backend or frontend).
