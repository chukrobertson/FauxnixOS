const St = imports.gi.St;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;

const TEMPLATES = [
    {id: 'coding', name: 'Coding'},
    {id: 'ml-python', name: 'ML / Python'},
    {id: 'writing', name: 'Writing'},
    {id: 'documents', name: 'Documents'},
    {id: 'research', name: 'Research'},
    {id: 'audio', name: 'Audio'},
    {id: 'image-video', name: 'Image/Video'},
    {id: 'gaming', name: 'Gaming'},
    {id: 'emulation', name: 'Emulation'},
    {id: 'dvd-ripping', name: 'DVD Ripping'},
];

let _indicator = null;

function _runWsctl(args) {
    try {
        Gio.Subprocess.new(
            ['/home/chxk/.local/bin/wsctl'].concat(args),
            Gio.SubprocessFlags.NONE
        );
    } catch (e) {
        log('[fennix] wsctl error: ' + e);
    }
}

function _refreshThreads(indicator) {
    try {
        let proc = Gio.Subprocess.new(
            ['sudo', 'machinectl', 'list', '--no-legend'],
            Gio.SubprocessFlags.STDOUT_PIPE
        );
        proc.communicate_utf8_async(null, null, function(proc, result) {
            let [, stdout] = proc.communicate_utf8_finish(result);
            let lines = stdout.trim().split('\n').filter(function(l) { return l.trim(); });
            let count = lines.length;
            indicator._label.set_text(count > 0 ? ' ' + count : '');

            indicator._threadSection.removeAll();
            if (count === 0) {
                let empty = new PopupMenu.PopupMenuItem('No threads running');
                empty.setSensitive(false);
                indicator._threadSection.addMenuItem(empty);
                return;
            }

            let title = new PopupMenu.PopupMenuItem('Running (' + count + ')');
            title.setSensitive(false);
            indicator._threadSection.addMenuItem(title);

            for (let i = 0; i < lines.length; i++) {
                let parts = lines[i].trim().split(/\s+/);
                let name = parts[0] || 'unknown';
                let item = new PopupMenu.PopupSubMenuMenuItem(name);

                let shellItem = new PopupMenu.PopupMenuItem('Attach (shell)');
                shellItem.connect('activate', function() {
                    _runWsctl(['attach', name]);
                });
                item.menu.addMenuItem(shellItem);

                let statusItem = new PopupMenu.PopupMenuItem('View status');
                statusItem.connect('activate', function() {
                    Gio.Subprocess.new(
                        ['gnome-terminal', '--', 'wsctl', 'status', name],
                        Gio.SubprocessFlags.NONE
                    );
                });
                item.menu.addMenuItem(statusItem);

                let stopItem = new PopupMenu.PopupMenuItem('Stop thread');
                stopItem.connect('activate', function() {
                    _runWsctl(['stop', name]);
                });
                item.menu.addMenuItem(stopItem);

                indicator._threadSection.addMenuItem(item);
            }
        });
    } catch (e) {
        log('[fennix] refresh error: ' + e);
    }
}

function enable() {
    _indicator = new PanelMenu.Button(0.0, 'Fennix Threads');

    let box = new St.BoxLayout({ style_class: 'panel-status-menu-box' });
    let icon = new St.Icon({
        icon_name: 'view-grid-symbolic',
        style_class: 'system-status-icon',
    });
    box.add_child(icon);

    _indicator._label = new St.Label({
        text: '',
        y_align: St.Align.MIDDLE,
    });
    box.add_child(_indicator._label);
    _indicator.add_child(box);

    for (let i = 0; i < TEMPLATES.length; i++) {
        let t = TEMPLATES[i];
        let item = new PopupMenu.PopupMenuItem('Create ' + t.name + ' thread');
        item.connect('activate', function() {
            _runWsctl(['ask', t.name + ' development work', '--profile', 'win11']);
        });
        _indicator.menu.addMenuItem(item);
    }

    _indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    _indicator._threadSection = new PopupMenu.PopupMenuSection();
    _indicator.menu.addMenuItem(_indicator._threadSection);

    _indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

    let dashItem = new PopupMenu.PopupMenuItem('Dashboard');
    dashItem.connect('activate', function() {
        Gio.Subprocess.new(
            ['gnome-terminal', '--', 'wsctl', 'dashboard'],
            Gio.SubprocessFlags.NONE
        );
    });
    _indicator.menu.addMenuItem(dashItem);

    Main.panel.addToStatusArea('fennix-threads', _indicator);

    _refreshThreads(_indicator);
    GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, function() {
        _refreshThreads(_indicator);
        return GLib.SOURCE_CONTINUE;
    });

    log('[fennix] enabled');
}

function disable() {
    if (_indicator) {
        _indicator.destroy();
        _indicator = null;
    }
    log('[fennix] disabled');
}
