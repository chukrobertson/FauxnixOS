import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import St from 'gi://St';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

const TEMPLATES = [
    {id: 'coding', name: 'Coding', icon: 'applications-development-symbolic'},
    {id: 'ml-python', name: 'ML / Python', icon: 'applications-science-symbolic'},
    {id: 'writing', name: 'Writing', icon: 'applications-office-symbolic'},
    {id: 'documents', name: 'Documents', icon: 'x-office-document-symbolic'},
    {id: 'research', name: 'Research', icon: 'web-browser-symbolic'},
    {id: 'audio', name: 'Audio', icon: 'applications-multimedia-symbolic'},
    {id: 'image-video', name: 'Image/Video', icon: 'applications-graphics-symbolic'},
    {id: 'gaming', name: 'Gaming', icon: 'applications-games-symbolic'},
    {id: 'web-dev', name: 'Web Dev', icon: 'applications-web-symbolic'},
    {id: 'rust-dev', name: 'Rust Dev', icon: 'applications-engineering-symbolic'},
];

const PROFILES = [
    {id: 'win11', name: 'Windows 11'},
    {id: 'macos', name: 'macOS'},
    {id: 'headless', name: 'Headless'},
];


class ThreadIndicator extends PanelMenu.Button {
    constructor() {
        super(0.0, 'Fennix Threads');
        this._threads = [];

        let box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        let icon = new St.Icon({
            icon_name: 'view-grid-symbolic',
            style_class: 'system-status-icon',
        });
        box.add_child(icon);
        this._label = new St.Label({
            text: '',
            y_align: St.Align.MIDDLE,
        });
        box.add_child(this._label);
        this.add_child(box);

        this._rebuildMenu();
        this._refreshThreads();
        this._timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            this._refreshThreads();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _rebuildMenu() {
        this.menu.removeAll();

        for (let t of TEMPLATES) {
            let item = new PopupMenu.PopupMenuItem(`Create ${t.name} thread`);
            item.connect('activate', () => {
                this._runWsctl(['ask', t.name + ' development work', '--profile', 'win11']);
            });
            this.menu.addMenuItem(item);
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._threadSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._threadSection);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let statusItem = new PopupMenu.PopupMenuItem('Dashboard');
        statusItem.connect('activate', () => {
            this._runWsctl(['dashboard']);
        });
        this.menu.addMenuItem(statusItem);

        let searchItem = new PopupMenu.PopupMenuItem('Search threads...');
        searchItem.connect('activate', () => {
            Main.overview.show();
            Main.overview.searchEntry.text = 'faux ';
        });
        this.menu.addMenuItem(searchItem);
    }

    _runWsctl(args) {
        try {
            let proc = Gio.Subprocess.new(
                ['/home/chxk/.local/bin/wsctl', ...args],
                Gio.SubprocessFlags.NONE
            );
        } catch (e) {
            log('[fennix] wsctl error: ' + e);
        }
    }

    _refreshThreads() {
        try {
            let proc = Gio.Subprocess.new(
                ['sudo', 'machinectl', 'list', '--no-legend'],
                Gio.SubprocessFlags.STDOUT_PIPE
            );
            proc.communicate_utf8_async(null, null, (proc, result) => {
                let [, stdout] = proc.communicate_utf8_finish(result);
                let lines = stdout.trim().split('\n').filter(l => l.trim());
                let count = lines.length;
                this._label.set_text(count > 0 ? ` ${count}` : '');

                this._threadSection.removeAll();
                if (count === 0) {
                    let empty = new PopupMenu.PopupMenuItem('No threads running');
                    empty.setSensitive(false);
                    this._threadSection.addMenuItem(empty);
                    return;
                }

                let title = new PopupMenu.PopupMenuItem(`Running (${count})`);
                title.setSensitive(false);
                this._threadSection.addMenuItem(title);

                for (let line of lines) {
                    let parts = line.trim().split(/\s+/);
                    let name = parts[0] || 'unknown';
                    let item = new PopupMenu.PopupSubMenuMenuItem(name);

                    let shellItem = new PopupMenu.PopupMenuItem('Attach (shell)');
                    shellItem.connect('activate', () => {
                        this._runWsctl(['attach', name]);
                    });
                    item.menu.addMenuItem(shellItem);

                    let vncItem = new PopupMenu.PopupMenuItem('Open in VNC (waypipe)');
                    vncItem.connect('activate', () => {
                        Gio.Subprocess.new(
                            ['waypipe', 'ssh', `chxk@${name}.local`],
                            Gio.SubprocessFlags.NONE
                        );
                    });
                    item.menu.addMenuItem(vncItem);

                    let statusItem = new PopupMenu.PopupMenuItem('View status');
                    statusItem.connect('activate', () => {
                        Gio.Subprocess.new(
                            ['gnome-terminal', '--', 'wsctl', 'status', name],
                            Gio.SubprocessFlags.NONE
                        );
                    });
                    item.menu.addMenuItem(statusItem);

                    let stopItem = new PopupMenu.PopupMenuItem('Stop thread');
                    stopItem.connect('activate', () => {
                        this._runWsctl(['stop', name]);
                    });
                    item.menu.addMenuItem(stopItem);

                    this._threadSection.addMenuItem(item);
                }
            });
        } catch (e) {
            log('[fennix] refresh error: ' + e);
        }
    }

    destroy() {
        if (this._timeout) {
            GLib.source_remove(this._timeout);
            this._timeout = null;
        }
        super.destroy();
    }
}


export default class FennixExtension extends Extension {
    enable() {
        this._indicator = new ThreadIndicator();
        Main.panel.addToStatusArea('fennix-threads', this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
