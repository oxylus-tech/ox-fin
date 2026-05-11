TODO
====

- models:

    - CapabilitySet -> derive_caps arg to ease api usage

- migrations/signal:

    - Provide a way to specify default Capabilities which will be
      created on migration.
    - create an agent for each user and each group

- views:

    - views for: Agent (list, detail -> Permission required), Reference (list, detail, delete)
    - Reference: derive
    - viewsets for: Reference, Capability

- urls:

    - get_object_urls:
        - urls for the object
        - urls for the object's reference
    - get_reference_urls: provide urls for Reference class

- serializers:

    - simple serializers

- filtersets:

    - for: Reference, Capability, Agent, Object

- forms
- admin
