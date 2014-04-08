DBus-to-CIM code generator
==========================

Original purpose of this code was to extend glib gdbus-codegen tool to generate
providers, which would 1:1 map CIM to DBus interfaces of a service.

Current state is just mof file generator. Even this mof file must be heavily
modified to resemble CIM-like classes.
