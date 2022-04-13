
# Save Restore Layout

This plugin implements footprint modules or snippets feature. The plugin saves partial layout corresponding to footprints from one hirearchical sheet so that it can be restored in other projects. All projects have to use the same hierarchical sheet schematics. If the schematics has been edited, the plugin will refuse to restore the layout. So in projects where you need to change the schematics slightly, first restore the layout and then change the schematics.

## Installation

The preferred way to install the plugin is via KiCad's PCM (Plugin and Content Manager). Installation on non-networked
can be done by downloading the latest [release](https://github.com/MitjaNemec/SaveRestoreLayout/releases) and installing
in with PCM with `Install from file` option 

## Warning

There is a [bug](https://gitlab.com/kicad/code/kicad/-/issues/11076) in KiCad when reusing hierarchical sheets which contain multiple instances of same nested sheet. the bug causes unintended changes in schematics files, which will cause the plugin to fail. Please read the bug description which also contains a workaround for such cases.



