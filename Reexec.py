import sublime, sublime_plugin
import os, sys, re
import threading
import subprocess
import functools
import time
import traceback
import posixpath
import difflib

def plugin_loaded():
    """This function checks settings for sanity."""
    plugin_settings = sublime.load_settings("Reexec.sublime-settings")
    if not plugin_settings.get('ssh_path', 'ssh'):
        raise ValueError('reexec: ssh_path must not be empty. Please check the settings.')
    if not plugin_settings.get('rsync_path', 'rsync'):
        raise ValueError('reexec: rsync_path must not be empty. Please check the settings.')
    servers = plugin_settings.get("servers", [])
    unique_names = set()
    required_parameters = ['name', 'root_directory', 'host']
    nonempty_parameters = ['name', 'root_directory', 'host']
    for s in servers:
        for param in required_parameters:
            if param not in s:
                raise ValueError('reexec: "{0}" parameter is required. Please check the settings.'.format(param))
        for param in nonempty_parameters:
            if param in s and len(s[param])==0:
                raise ValueError('reexec: "{0}" parameter must not be empty. Please check the settings.'.format(param))
        if s['name'] in unique_names:
            raise ValueError('reexec: duplicate "{0}" servers'.format(s['name']))
        unique_names.add(s['name'])


def getRelativePath(projectPath, projectName=None):
    """This function returns path of the projectPath directory relative
    to the folder named projectName which is supposed to be a part of the
    projectPath; if it is not the case, then relative path is just the last
    directory in the projectPath."""
    if projectPath.endswith(os.path.sep):
        projectPath = projectPath[:-1]
    if not projectName:
        return os.path.split(projectPath)[1]
    else:
        relPath = ''
        p = projectPath
        while True:
            p, currentDir = os.path.split(p)
            if not currentDir:
                break
            relPath = posixpath.join(currentDir, relPath)
            if currentDir==projectName:
                return relPath
        return os.path.split(projectPath)[1]


def fullsplit(path, path_module):
    if path.endswith(path_module.sep):
        path = path[:-1]
    p = []
    while True:
        path, directory = path_module.split(path)
        if not directory:
            if path:
                p.insert(0, path)
            break
        p.insert(0, directory)
    return p


def adjust_path(a, path_mod_a, b, path_mod_b):
    diff = list(difflib.ndiff(fullsplit(a, path_mod_a), fullsplit(b, path_mod_b)))
    if diff[-1][0]==' ':
        return b
    else:
        relative_path = []
        for s in reversed(diff):
            if s[0]!=' ':
                relative_path.insert(0, s[2:])
            else:
                break
    return path_mod_b.join(b, *relative_path)


def cygwinize(path):
    """This function makes cygwin-style paths (e.g. /cygdrive/c/path/to/dir) from the
    ordinary Windows paths (e.g. c:\\path\\to\\dir)."""
    return re.sub(r'(\w):', '/cygdrive/\\1', path.replace('\\', '/'))


class ProcessListener(object):
    def on_data(self, proc, data):
        pass

    def on_finished(self, proc):
        pass


# Encapsulates subprocess.Popen, forwarding stdout to a supplied
# ProcessListener (on a separate thread)
class AsyncProcess(object):
    def __init__(self, cmd, shell_cmd, env, listener,
            # "path" is an option in build systems
            path="",
            # "shell" is an options in build systems
            shell=False):

        if not shell_cmd and not cmd:
            raise ValueError("shell_cmd or cmd is required")

        if shell_cmd and not isinstance(shell_cmd, str):
            raise ValueError("shell_cmd must be a string")

        self.listener = listener
        self.killed = False

        self.start_time = time.time()

        # Hide the console window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Set temporary PATH to locate executable in cmd
        if path:
            old_path = os.environ["PATH"]
            # The user decides in the build system whether he wants to append $PATH
            # or tuck it at the front: "$PATH;C:\\new\\path", "C:\\new\\path;$PATH"
            os.environ["PATH"] = os.path.expandvars(path)

        proc_env = os.environ.copy()
        proc_env.update(env)
        for k, v in proc_env.items():
            proc_env[k] = os.path.expandvars(v)

        if shell_cmd and sys.platform == "win32":
            # Use shell=True on Windows, so shell_cmd is passed through with the correct escaping
            self.proc = subprocess.Popen(shell_cmd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=True)
        elif shell_cmd and sys.platform == "darwin":
            # Use a login shell on OSX, otherwise the users expected env vars won't be setup
            self.proc = subprocess.Popen(["/bin/bash", "-l", "-c", shell_cmd], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=False)
        elif shell_cmd and sys.platform == "linux":
            # Explicitly use /bin/bash on Linux, to keep Linux and OSX as
            # similar as possible. A login shell is explicitly not used for
            # linux, as it's not required
            self.proc = subprocess.Popen(["/bin/bash", "-c", shell_cmd], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=False)
        else:
            # Old style build system, just do what it asks
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=shell)

        if path:
            os.environ["PATH"] = old_path

        if self.proc.stdout:
            threading.Thread(target=self.read_stdout).start()

        if self.proc.stderr:
            threading.Thread(target=self.read_stderr).start()

    def kill(self):
        if not self.killed:
            self.killed = True
            if sys.platform == "win32":
                # terminate would not kill process opened by the shell cmd.exe, it will only kill
                # cmd.exe leaving the child running
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen("taskkill /PID " + str(self.proc.pid), startupinfo=startupinfo)
            else:
                self.proc.terminate()
            self.listener = None

    def poll(self):
        return self.proc.poll() == None

    def exit_code(self):
        return self.proc.poll()

    def read_stdout(self):
        while True:
            data = os.read(self.proc.stdout.fileno(), 2**15)

            if len(data) > 0:
                if self.listener:
                    self.listener.on_data(self, data)
            else:
                self.proc.stdout.close()
                if self.listener:
                    self.listener.on_finished(self)
                break

    def read_stderr(self):
        while True:
            data = os.read(self.proc.stderr.fileno(), 2**15)

            if len(data) > 0:
                if self.listener:
                    self.listener.on_data(self, data)
            else:
                self.proc.stderr.close()
                break


class base_exec(sublime_plugin.WindowCommand, ProcessListener):
    """Original unchanged ExecCommand, just renamed it so it does not clutter the namespace."""
    def run(self, cmd = None, shell_cmd = None, file_regex = "", line_regex = "", working_dir = "",
            encoding = "utf-8", env = {}, quiet = False, kill = False,
            word_wrap = True, syntax = "Packages/Text/Plain text.tmLanguage",
            # Catches "path" and "shell"
            **kwargs):

        if kill:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_string(None, "[Cancelled]")
            return

        if not hasattr(self, 'output_view'):
            # Try not to call get_output_panel until the regexes are assigned
            self.output_view = self.window.create_output_panel("reexec")

        # Default the to the current files directory if no working directory was given
        if (working_dir == "" and self.window.active_view()
                        and self.window.active_view().file_name()):
            working_dir = os.path.dirname(self.window.active_view().file_name())

        self.output_view.settings().set("result_file_regex", file_regex)
        self.output_view.settings().set("result_line_regex", line_regex)
        self.output_view.settings().set("result_base_dir", working_dir)
        self.output_view.settings().set("word_wrap", word_wrap)
        self.output_view.settings().set("line_numbers", False)
        self.output_view.settings().set("gutter", False)
        self.output_view.settings().set("scroll_past_end", False)
        self.output_view.assign_syntax(syntax)

        # Call create_output_panel a second time after assigning the above
        # settings, so that it'll be picked up as a result buffer
        self.window.create_output_panel("reexec")

        self.encoding = encoding
        self.quiet = quiet

        self.proc = None
        if not self.quiet:
            if shell_cmd:
                print("Running " + shell_cmd)
            else:
                print("Running " + " ".join(cmd))
            sublime.status_message("Building")

        show_panel_on_build = sublime.load_settings("Preferences.sublime-settings").get("show_panel_on_build", True)
        if show_panel_on_build:
            self.window.run_command("show_panel", {"panel": "output.reexec"})

        merged_env = env.copy()
        if self.window.active_view():
            user_env = self.window.active_view().settings().get('build_env')
            if user_env:
                merged_env.update(user_env)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if working_dir != "":
            os.chdir(working_dir)

        self.debug_text = ""
        if shell_cmd:
            self.debug_text += "[shell_cmd: " + shell_cmd + "]\n"
        else:
            self.debug_text += "[cmd: " + str(cmd) + "]\n"
        self.debug_text += "[dir: " + str(os.getcwd()) + "]\n"
        if "PATH" in merged_env:
            self.debug_text += "[path: " + str(merged_env["PATH"]) + "]"
        else:
            self.debug_text += "[path: " + str(os.environ["PATH"]) + "]"

        try:
            # Forward kwargs to AsyncProcess
            self.proc = AsyncProcess(cmd, shell_cmd, merged_env, self, **kwargs)
        except Exception as e:
            self.append_string(None, str(e) + "\n")
            self.append_string(None, self.debug_text + "\n")
            if not self.quiet:
                self.append_string(None, "[Finished]")

    def is_enabled(self, kill = False):
        if kill:
            return hasattr(self, 'proc') and self.proc and self.proc.poll()
        else:
            return True

    def append_data(self, proc, data):
        if proc != self.proc:
            # a second call to exec has been made before the first one
            # finished, ignore it instead of intermingling the output.
            if proc:
                proc.kill()
            return

        try:
            str = data.decode(self.encoding)
        except:
            str = "[Decode error - output not " + self.encoding + "]\n"
            proc = None

        # Normalize newlines, Sublime Text always uses a single \n separator
        # in memory.
        str = str.replace('\r\n', '\n').replace('\r', '\n')

        self.output_view.run_command('append', {'characters': str, 'force': True, 'scroll_to_end': True})

    def append_string(self, proc, str):
        self.append_data(proc, str.encode(self.encoding))

    def finish(self, proc):
        if not self.quiet:
            elapsed = time.time() - proc.start_time
            exit_code = proc.exit_code()
            if exit_code == 0 or exit_code == None:
                self.append_string(proc,
                    ("[Finished in %.1fs]" % (elapsed)))
            else:
                self.append_string(proc, ("[Finished in %.1fs with exit code %d]\n"
                    % (elapsed, exit_code)))
                self.append_string(proc, self.debug_text)

        if proc != self.proc:
            return

        errs = self.output_view.find_all_results()
        if len(errs) == 0:
            sublime.status_message("Build finished")
        else:
            sublime.status_message(("Build finished with %d errors") % len(errs))

    def on_data(self, proc, data):
        sublime.set_timeout(functools.partial(self.append_data, proc, data), 0)

    def on_finished(self, proc):
        sublime.set_timeout(functools.partial(self.finish, proc), 0)


class ReexecCommand(base_exec):
    def run(self, cmd = None, shell_cmd = None, file_regex = "", line_regex = "", working_dir = "",
            encoding = "utf-8", env = {}, quiet = False, kill = False,
            word_wrap = True, syntax = "Packages/Text/Plain text.tmLanguage",
            # These are new parameters:
            remote_server = None, remote_cmd = None, excludes = [],
            local_rsync_root = None, remote_rsync_root = None,
            # Catches "path" and "shell"
            **kwargs):

        self.cmd_list = []
        self.project_path = None
        self.file_regex = file_regex
        # if remote server is not specified, no remote commands will be executed
        if remote_server:
            plugin_settings = sublime.load_settings("Reexec.sublime-settings")
            servers = plugin_settings.get("servers", [])
            found_by_name = [s for s in servers if s['name']==remote_server]
            if len(found_by_name)==0:
                sublime.message_dialog('reexec: unknown remote server "{0}"'.format(remote_server))
                return

            server_settings = found_by_name[0]
            remote_rsync_root = remote_rsync_root or server_settings['root_directory']
            # if project exists, then use $project_path as local_rsync_root
            # else, use $file_path -- that is, rsync only current file
            if sublime.active_window().project_file_name():
                project_path, project_name = os.path.split(sublime.active_window().project_file_name())
                project_name = os.path.splitext(project_name)[0]
                self.project_path = project_path
                if sublime.platform()=='windows':
                    project_path = cygwinize(project_path)
                if not project_path.endswith('/'):
                    project_path += '/'
                local_rsync_root = project_path
                remote_rsync_root = posixpath.join(remote_rsync_root,
                    getRelativePath(self.project_path, project_name))
                self.remote_rsync_root = remote_rsync_root
            elif sublime.active_window().active_view().file_name():
                local_rsync_root = sublime.active_window().active_view().file_name()
                self.project_path = local_rsync_root
                if sublime.platform()=='windows':
                    local_rsync_root = cygwinize(local_rsync_root)
            else:
                sublime.message_dialog('reexec: no active project or current file not saved yet.')
                return

            default_rsync_opts = '-avr'
            # for Windows it's good to set permissions manually so that
            # ordinary files do not get execution permissions
            if sublime.platform()=='windows':
                default_rsync_opts += ' --chmod=Du=rwX,Dgo=rX,Fu=rw,Fgo=r,Fugo-x'

            actual_settings = {\
                'port': '',
                'user': '',
                'ssh_options': plugin_settings.get('ssh_options', ''),
                'rsync_options': plugin_settings.get('rsync_options', default_rsync_opts),
                'ssh_path': plugin_settings.get('ssh_path', 'ssh'),
                'rsync_path': plugin_settings.get('rsync_path', 'rsync'),
                'private_key': '',
                'remote_cmd': remote_cmd
            }

            # Default values will be rewritten with the values from server_settings
            actual_settings.update(server_settings)
            actual_settings['src'] = local_rsync_root
            actual_settings['dst'] = remote_rsync_root
            if actual_settings['port']:
                actual_settings['ssh_options'] += ' -p'+actual_settings['port']
            if actual_settings['private_key']:
                if sublime.platform()=='windows':
                    actual_settings['private_key'] = cygwinize(actual_settings['private_key'])
                actual_settings['ssh_options'] += ' -i ' + actual_settings['private_key']
            if actual_settings['user']:
                actual_settings['user'] += '@'
            for e in excludes:
                actual_settings['rsync_options'] += ' --exclude="{0}"'.format(e)

            mkdir_cmd = '{ssh_path} {ssh_options} {user}{host} mkdir -p {dst}'.format(\
                **actual_settings)
            rsync_cmd = '{rsync_path} {rsync_options} -e "{ssh_path} {ssh_options}" {src} {user}{host}:{dst}'.format(\
                **actual_settings)
            self.cmd_list.append(mkdir_cmd)
            self.cmd_list.append(rsync_cmd)
            if remote_cmd:
                build_cmd = '{ssh_path} {ssh_options} {user}{host} "cd {dst} && {remote_cmd}"'.format(\
                    **actual_settings)
                self.cmd_list.append(build_cmd)

        # create a closure to simplify command execution
        self.run_func = lambda par_cmd, par_shell_cmd: base_exec.run(self,
            par_cmd, par_shell_cmd,
            file_regex, line_regex, working_dir, encoding, env,
            quiet, kill, word_wrap, syntax, **kwargs)

        if cmd or shell_cmd:
            self.run_func(cmd, shell_cmd)
        else:
            self.run_func(None, self.cmd_list.pop(0))

    def append_data(self, proc, data):
        if proc != self.proc:
            # a second call to exec has been made before the first one
            # finished, ignore it instead of intermingling the output.
            if proc:
                proc.kill()
            return

        try:
            str = data.decode(self.encoding)
        except:
            str = "[Decode error - output not " + self.encoding + "]\n"
            proc = None

        # Normalize newlines, Sublime Text always uses a single \n separator
        # in memory.
        str = str.replace('\r\n', '\n').replace('\r', '\n')
        if self.project_path and self.file_regex:
            strlines = str.splitlines(True)
            changed = False
            for i,line in enumerate(strlines):
                m = re.match(self.file_regex, line)
                if m:
                    path = m.group(1)
                    line = adjust_path(path, posixpath, self.project_path, os.path) + line[len(m.group(1)):]
                    # self.output_view.run_command('append', {'characters': '***{0}***\n'.format(line)})
                    strlines[i] = line
                    changed = True
            if changed:
                str = ''.join(strlines)

        self.output_view.run_command('append', {'characters': str, 'force': True, 'scroll_to_end': True})

    def finish(self, proc):
        if len(self.cmd_list):
            self.run_func(None, self.cmd_list.pop(0))
        else:
            base_exec.finish(self, proc)
