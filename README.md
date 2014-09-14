reexec
======

A plugin for Sublime Text 3 which offers a replacement for the standard `exec` and allows rsyncing to a remote server and remote compilation.


History
=======

I developed this plugin after I got tired of wasting time and attention on remote cross-compilation which involved copying the project files, building, peeping the console for the errors, fixing, copying again, rebuilding and so on. I work with Sublime Text and I need to build my projects for a certain Linux distribution. The easiest thing to accomplish this task is to setup a build server that would mimic the target machine -- moreover, this server can be a virtual machine running on any of the major operating systems. Given that Sublime Text is cross-platform, it becomes possible to work on the project from any desirable system, which is a great virtue for I work from both Linux and Windows interchangeably.


Features
========

* Extends built-in `exec` functionality; compatible with `exec`;
* Copies the project files to a remote directory using rsync;
* Executes an arbitrary (build) command on a remote server in the project directory;
* Passes the build output to Sublime Text so you can navigate errors with `F4` as usual;
* Works with either Sublime Text projects or single files (good for small test programs);
* Works with many servers: you can choose a different server for every project.


Installation
============

Prerequisites
-------------

* You must have `ssh` and `rsync` installed on your system. Windows: I use [cwRsync](https://www.itefix.net/cwrsync) and `ssh` bundled with it; also Windows users should either add the paths to the `cwRsync.exe` and `ssh.exe` to the `PATH` environment variable, or set these paths in `reexec` configuration file (see below).
* You must have a key for each of the servers you plan to use with `reexec`. Windows: you can generate a key pair using `ssh-keygen` from `cwRsync` package.

Setup Process
-------------

No one-click way to install yet. Clone the repository into your `Packages` folder:
* For Linux, it is `~/.config/sublime-text-3/Packages`;
* For Windows, it is `Data\Packages` relative to your Sublime Text installation directory.

I'm not sure about Mac OS X, sorry; you should figure this out yourself.


Configuration
=============

Plugin Configuration
--------------------

All configuration is done via `Packages -> Package Settings -> Reexec -> Settings - User` menu in Sublime Text. You can view default settings in `Packages -> Package Settings -> Reexec -> Settings - Default` menu.

Here is an example configuration:
```javascript
// plugin settings
{
```

Path to the `ssh` executable file. Leave as is for *nix, fill for Windows if not in `%PATH%`.
```javascript
	"ssh_path": "ssh",
```

SSH command line options. Should be self-explanatory. Note these will be overriden (not appended!) by the per-server settings.
```javascript
	"ssh_options": "",
```

`rsync` path and options. All the same here.
```javascript
	"rsync_path": "rsync", // path to rsync executable, mostly for Windows users
	"rsync_options": "-avr", // will be overriden by server settings if present
```

Server list configuration block.
```javascript
	"servers": [
		{
```

First, let's start with the mandatory parameters. `name` is the server name which is used to refer to the server in a build system.
```javascript
			"name": "My Build Server", // server name 
```

Root directory. This path must be specified as either a path relative to `~` for the `user` (see below) or as an absolute path (e.g. `/home/me/my/build/directory`).
```javascript
			"root_directory": "build",
```

Host name or IP address of the server and port to connect to. You can certainly use an alias from `.ssh/config` here.
```javascript
			"host": "192.168.1.2",
```
All the rest parameters are optional. They are listed with their default values here.
```javascript
			"port": "22",
```

Username to connect to the remote host. By default, `ssh` takes your current user name -- the same applies here, if blank or not present the current user name will be used.
```javascript
			"user": "",
```

For Windows: path to the private key. `ssh` included with `cwRsync` may or may not find your private key so it can be a good idea to specify this path explicitly.
```javascript
			"private_key": "",
```

These are not present by default. Remember that these settings override the plugin-wide settings.
```javascript
      "ssh_options": "",
      "rsync_options": "-avr"
		}
	]
}
```


Build System Configuration
--------------------------

As was mentioned earlier, `reexec` is build on top of `exec.py`. Thus, it supports the functionality of the latter and adds several options relevant to remote building. These are:

* `target` -- this setting should be set to `reexec` for the plugin to work.
* `remote_server` -- name of the server to choose from the list given in the plugin settings file (see above). If unspecified, all other `reexec`-specific options will be ignored and `reexec` will act just as `exec`.
* `remote_cmd` -- command to be executed on the server once the rsync job is done. This is the actual build command. Note for Windows users: `cwrsync` sets all the files and folders full (0777) permissions upon copying. This behaviour is overriden by `reexec` so that files are given 0644 permissions and folders are given 0755 permissions. This can render build scripts unable to execute. You can either override (again) `reexec`'s policy and give files full permissions, or, if you're using a build script, you can prepend the command that starts it, with a shell command, such as `sh build.sh`.
* `remote_rsync_root` -- a directory on the remote server where the project directory will be created. It overrides the default setting in the plugin configuration file.
* `excludes` -- list of file masks which are not to be copied to the server. Please refer to the rsync manual for more information.

