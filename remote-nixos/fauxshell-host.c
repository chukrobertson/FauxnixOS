#include <gtk/gtk.h>
#include <gtk-layer-shell.h>
#include <curl/curl.h>
#include <json-glib/json-glib.h>
#include <math.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define API_BASE "http://127.0.0.1:8756/api"
#define MAX_ROWS 4
#define FILE_ROWS 5
#define FILE_VIEW_ROWS 12
#define CONTINUITY_ROWS 6
#define THREAD_CARD_COUNT 8
#define LAUNCHER_HEIGHT 420
#define DESKTOP_ZOOM_MIN 0.25
#define DESKTOP_ZOOM_MAX 1.85
#define DESKTOP_ZOOM_STEP 1.18
#define MAP_WIDTH 4800
#define MAP_HEIGHT 3600

typedef struct {
    char *data;
    size_t size;
} Buffer;

typedef struct {
    double value;
    char title[16];
    GdkRGBA color;
} GaugeData;

typedef enum {
    NODE_HERO = 0,
    NODE_WEATHER,
    NODE_CALENDAR,
    NODE_CONTINUITY,
    NODE_APPS,
    NODE_NOTES,
    NODE_TELEMETRY,
    NODE_FILES,
    NODE_THREAD_FENNIX,
    NODE_THREAD_FAUXNIX,
    NODE_THREAD_FAUXDEX,
    NODE_THREAD_COWRITER,
    NODE_THREAD_ADMIN,
    NODE_THREAD_ROOT,
    NODE_THREAD_WEB,
    NODE_THREAD_TERMINAL,
    MAP_NODE_COUNT
} MapNodeId;

typedef enum {
    EDGE_HERO_CONTINUITY = 0,
    EDGE_CONTINUITY_NOTES,
    EDGE_CONTINUITY_APPS,
    EDGE_CONTINUITY_TELEMETRY,
    EDGE_CONTINUITY_FILES,
    EDGE_FILES_NOTES,
    EDGE_WEATHER_CALENDAR,
    EDGE_APPS_TELEMETRY,
    EDGE_CONTINUITY_THREAD_FENNIX,
    EDGE_CONTINUITY_THREAD_FAUXNIX,
    EDGE_CONTINUITY_THREAD_FAUXDEX,
    EDGE_CONTINUITY_THREAD_COWRITER,
    EDGE_CONTINUITY_THREAD_ADMIN,
    EDGE_CONTINUITY_THREAD_ROOT,
    EDGE_CONTINUITY_THREAD_WEB,
    EDGE_CONTINUITY_THREAD_TERMINAL,
    MAP_EDGE_COUNT
} MapEdgeId;

typedef struct {
    const char *id;
    const char *title;
    GtkWidget *widget;
    int x;
    int y;
    int width;
    int height;
} MapNode;

typedef struct {
    MapNodeId from;
    MapNodeId to;
    const char *label;
    gboolean active;
} MapEdge;

typedef struct {
    GtkWidget *greeting;
    GtkWidget *clock_line;
    GtkWidget *status_line;
    GtkWidget *weather_symbol;
    GtkWidget *weather_summary;
    GtkWidget *weather_location;
    GtkWidget *net_state;
    GtkWidget *audio_state;
    GtkWidget *power_state;
    GtkWidget *telemetry_detail;
    GtkWidget *notes_summary;
    GtkWidget *file_summary;
    GtkWidget *clipboard_preview;
    GtkWidget *calendar_title;
    GtkWidget *calendar_grid;
    GtkWidget *desktop_scroll;
    GtkWidget *map_canvas;
    GtkWidget *connection_layer;
    GtkWidget *cpu_gauge;
    GtkWidget *ram_gauge;
    GtkWidget *load_gauge;
    GtkWidget *battery_gauge;
    GtkWidget *continuity_rows[CONTINUITY_ROWS];
    GtkWidget *file_rows[FILE_ROWS];
    GtkWidget *note_rows[MAX_ROWS];
    GtkWidget *thread_meta[THREAD_CARD_COUNT];
    GtkWidget *thread_activity[THREAD_CARD_COUNT];
    char *clipboard_text;
    char *user;
    MapNode nodes[MAP_NODE_COUNT];
    MapEdge edges[MAP_EDGE_COUNT];
    double desktop_zoom;
    double pinch_base_zoom;
    int drag_node;
    double drag_start_root_x;
    double drag_start_root_y;
    int drag_start_x;
    int drag_start_y;
    int last_event_id;
} App;

typedef struct {
    GtkWidget *window;
    GtkWidget *status_line;
    GtkWidget *telemetry_line;
    GtkWidget *chat_entry;
    GtkWidget *chat_output;
    gboolean chat_busy;
    gboolean visible;
    int lock_fd;
} Launcher;

typedef struct {
    GtkWidget *window;
    GtkWidget *scope_label;
    GtkWidget *detail_title;
    GtkWidget *detail_meta;
    GtkWidget *preview_text;
    GtkWidget *preview_image;
    GtkWidget *thread_combo;
    GtkWidget *search_entry;
    GtkWidget *content_search;
    GtkWidget *action_status;
    GtkWidget *rows[FILE_VIEW_ROWS];
    char *paths[FILE_VIEW_ROWS];
    char *selected_path;
    char *root_filter;
} FilesView;

static void handle_shell_event(App *app, const char *event);
static gboolean launcher_update_summary(gpointer user_data);
static void launcher_send_chat(Launcher *launcher);
static void app_handle_clipboard_action(App *app, const char *action);
static gboolean text_has_content(const char *text);
static char *compact_clipboard_text(const char *text, glong limit);
static char *read_system_clipboard_text(void);
static char *clipboard_payload_json(const char *text);
static void app_handle_zoom_action(App *app, const char *action);
static void update_thread_cards(App *app, JsonArray *array);

static void set_label(GtkWidget *label, const char *text) {
    if (label != NULL) {
        gtk_label_set_text(GTK_LABEL(label), text != NULL ? text : "");
    }
}

static void set_status(App *app, const char *text) {
    set_label(app->status_line, text);
}

static double clamp_adjustment_value(GtkAdjustment *adjustment, double value, double content_size) {
    double lower = gtk_adjustment_get_lower(adjustment);
    double page = gtk_adjustment_get_page_size(adjustment);
    double upper = MAX(content_size, page);
    double max_value = MAX(lower, upper - page);
    return CLAMP(value, lower, max_value);
}

static gboolean app_overview_mode(App *app) {
    double zoom = app != NULL && app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    return zoom < 0.98 || zoom > 1.02;
}

static char *map_layout_path(void) {
    char *dir = g_build_filename(g_get_user_config_dir(), "fauxnix", NULL);
    g_mkdir_with_parents(dir, 0700);
    char *path = g_build_filename(dir, "card-map.ini", NULL);
    g_free(dir);
    return path;
}

static void app_save_map_positions(App *app) {
    if (app == NULL) {
        return;
    }
    GKeyFile *key_file = g_key_file_new();
    for (int i = 0; i < MAP_NODE_COUNT; i++) {
        MapNode *node = &app->nodes[i];
        if (node->id == NULL) {
            continue;
        }
        g_key_file_set_integer(key_file, node->id, "x", node->x);
        g_key_file_set_integer(key_file, node->id, "y", node->y);
    }

    char *path = map_layout_path();
    GError *error = NULL;
    if (!g_key_file_save_to_file(key_file, path, &error)) {
        if (error != NULL) {
            g_warning("failed to save card map: %s", error->message);
            g_error_free(error);
        }
    }
    g_free(path);
    g_key_file_unref(key_file);
}

static void app_load_map_positions(App *app) {
    if (app == NULL) {
        return;
    }
    char *path = map_layout_path();
    GKeyFile *key_file = g_key_file_new();
    GError *error = NULL;
    if (!g_key_file_load_from_file(key_file, path, G_KEY_FILE_NONE, &error)) {
        if (error != NULL) {
            g_error_free(error);
        }
        g_key_file_unref(key_file);
        g_free(path);
        return;
    }

    for (int i = 0; i < MAP_NODE_COUNT; i++) {
        MapNode *node = &app->nodes[i];
        if (node->id == NULL || !g_key_file_has_group(key_file, node->id)) {
            continue;
        }
        GError *x_error = NULL;
        GError *y_error = NULL;
        int x = g_key_file_get_integer(key_file, node->id, "x", &x_error);
        int y = g_key_file_get_integer(key_file, node->id, "y", &y_error);
        if (x_error == NULL && y_error == NULL) {
            node->x = CLAMP(x, 0, MAP_WIDTH - node->width);
            node->y = CLAMP(y, 0, MAP_HEIGHT - node->height);
        }
        if (x_error != NULL) {
            g_error_free(x_error);
        }
        if (y_error != NULL) {
            g_error_free(y_error);
        }
    }

    g_key_file_unref(key_file);
    g_free(path);
}

static void app_layout_map(App *app) {
    if (app == NULL || app->map_canvas == NULL) {
        return;
    }
    double zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    int canvas_w = MAX(800, (int)round(MAP_WIDTH * zoom));
    int canvas_h = MAX(600, (int)round(MAP_HEIGHT * zoom));
    gtk_widget_set_size_request(app->map_canvas, canvas_w, canvas_h);
    if (app->connection_layer != NULL) {
        gtk_widget_set_size_request(app->connection_layer, canvas_w, canvas_h);
        gtk_fixed_move(GTK_FIXED(app->map_canvas), app->connection_layer, 0, 0);
        gtk_widget_queue_draw(app->connection_layer);
    }

    for (int i = 0; i < MAP_NODE_COUNT; i++) {
        MapNode *node = &app->nodes[i];
        if (node->widget == NULL) {
            continue;
        }
        int x = (int)round(node->x * zoom);
        int y = (int)round(node->y * zoom);
        gtk_widget_set_size_request(node->widget, node->width, node->height);
        gtk_fixed_move(GTK_FIXED(app->map_canvas), node->widget, x, y);
        if (app_overview_mode(app)) {
            gtk_widget_hide(node->widget);
        } else {
            gtk_widget_show(node->widget);
        }
    }
}

static void app_set_desktop_zoom(App *app, double zoom, double focus_x, double focus_y) {
    if (app == NULL || app->map_canvas == NULL || app->desktop_scroll == NULL) {
        return;
    }
    double old_zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    double next_zoom = CLAMP(zoom, DESKTOP_ZOOM_MIN, DESKTOP_ZOOM_MAX);
    if (fabs(next_zoom - old_zoom) < 0.001) {
        return;
    }

    GtkAdjustment *hadj = gtk_scrolled_window_get_hadjustment(GTK_SCROLLED_WINDOW(app->desktop_scroll));
    GtkAdjustment *vadj = gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(app->desktop_scroll));
    double old_h = hadj != NULL ? gtk_adjustment_get_value(hadj) : 0.0;
    double old_v = vadj != NULL ? gtk_adjustment_get_value(vadj) : 0.0;
    double anchor_x = old_h + MAX(0.0, focus_x);
    double anchor_y = old_v + MAX(0.0, focus_y);
    double factor = next_zoom / old_zoom;

    app->desktop_zoom = next_zoom;
    app_layout_map(app);

    int canvas_w = MAX(800, (int)round(MAP_WIDTH * next_zoom));
    int canvas_h = MAX(600, (int)round(MAP_HEIGHT * next_zoom));

    if (hadj != NULL) {
        gtk_adjustment_set_value(hadj, clamp_adjustment_value(hadj, (anchor_x * factor) - focus_x, canvas_w));
    }
    if (vadj != NULL) {
        gtk_adjustment_set_value(vadj, clamp_adjustment_value(vadj, (anchor_y * factor) - focus_y, canvas_h));
    }

    char *status = g_strdup_printf("Desktop zoom %.0f%%", next_zoom * 100.0);
    set_status(app, status);
    g_free(status);
}

static void app_handle_zoom_action(App *app, const char *action) {
    GtkAllocation allocation = {0, 0, 0, 0};
    if (app != NULL && app->desktop_scroll != NULL) {
        gtk_widget_get_allocation(app->desktop_scroll, &allocation);
    }
    double focus_x = allocation.width > 0 ? allocation.width / 2.0 : 640.0;
    double focus_y = allocation.height > 0 ? allocation.height / 2.0 : 360.0;
    double current = app != NULL && app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    if (g_strcmp0(action, "zoom:in") == 0) {
        app_set_desktop_zoom(app, current * DESKTOP_ZOOM_STEP, focus_x, focus_y);
    } else if (g_strcmp0(action, "zoom:out") == 0) {
        app_set_desktop_zoom(app, current / DESKTOP_ZOOM_STEP, focus_x, focus_y);
    } else if (g_strcmp0(action, "zoom:reset") == 0 || g_strcmp0(action, "zoom:home") == 0) {
        app_set_desktop_zoom(app, 1.0, focus_x, focus_y);
    }
}

static void add_class(GtkWidget *widget, const char *name) {
    GtkStyleContext *context = gtk_widget_get_style_context(widget);
    gtk_style_context_add_class(context, name);
}

static void enable_glass_window(GtkWidget *window, const char *class_name, double opacity) {
    if (window == NULL) {
        return;
    }
    GdkScreen *screen = gtk_widget_get_screen(window);
    GdkVisual *visual = screen != NULL ? gdk_screen_get_rgba_visual(screen) : NULL;
    if (visual != NULL) {
        gtk_widget_set_visual(window, visual);
    }
    gtk_widget_set_app_paintable(window, TRUE);
    if (opacity > 0.0 && opacity < 1.0) {
        gtk_widget_set_opacity(window, opacity);
    }
    if (class_name != NULL && class_name[0] != '\0') {
        add_class(window, class_name);
    }
}

static void spawn_command(const char *command) {
    GError *error = NULL;
    if (!g_spawn_command_line_async(command, &error)) {
        if (error != NULL) {
            g_warning("fauxshell action failed: %s: %s", command, error->message);
            g_error_free(error);
        }
    }
}

static char *runtime_path(const char *name) {
    const char *runtime = g_getenv("XDG_RUNTIME_DIR");
    if (runtime == NULL || runtime[0] == '\0') {
        runtime = "/tmp";
    }
    char *dir = g_build_filename(runtime, "fennix", NULL);
    g_mkdir_with_parents(dir, 0700);
    char *path = g_build_filename(dir, name, NULL);
    g_free(dir);
    return path;
}

static int acquire_named_lock(const char *name) {
    char *path = runtime_path(name);
    int fd = open(path, O_RDWR | O_CREAT, 0600);
    g_free(path);
    if (fd < 0) {
        return -1;
    }
    if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
        close(fd);
        return -2;
    }
    return fd;
}

static gboolean write_launcher_command(const char *command) {
    char *path = runtime_path("native-launcher-command");
    gboolean ok = g_file_set_contents(path, command, -1, NULL);
    g_free(path);
    return ok;
}

static void request_launcher_toggle(void) {
    int fd = acquire_named_lock("fauxshell-launcher.lock");
    gboolean launcher_running = fd == -2;
    if (fd >= 0) {
        close(fd);
    }
    write_launcher_command(launcher_running ? "toggle" : "show");
    if (!launcher_running) {
        spawn_command("/run/current-system/sw/bin/fauxshell-host --launcher");
    }
}

static void run_action(const char *action) {
    if (g_strcmp0(action, "thread:web") == 0) {
        spawn_command("fauxnix-thread web");
    } else if (g_strcmp0(action, "thread:fennix") == 0) {
        spawn_command("fennix-gui");
    } else if (g_strcmp0(action, "thread:fauxnix") == 0) {
        spawn_command("fauxnix-thread fauxnix");
    } else if (g_strcmp0(action, "thread:fauxdex") == 0) {
        spawn_command("fauxnix-thread fauxdex");
    } else if (g_strcmp0(action, "thread:cowriter") == 0) {
        spawn_command("fauxnix-thread cowriter");
    } else if (g_strcmp0(action, "thread:admin") == 0) {
        spawn_command("fauxnix-thread admin");
    } else if (g_strcmp0(action, "thread:root") == 0) {
        spawn_command("fauxnix-thread root");
    } else if (g_strcmp0(action, "thread:terminal") == 0) {
        spawn_command("fauxnix-thread terminal");
    } else if (g_strcmp0(action, "threads:menu") == 0) {
        spawn_command("fauxnix-thread menu");
    } else if (g_strcmp0(action, "apps") == 0) {
        spawn_command("rofi -show drun");
    } else if (g_strcmp0(action, "notes") == 0) {
        spawn_command("fennix-gui --notes");
    } else if (g_strcmp0(action, "files") == 0) {
        spawn_command("/run/current-system/sw/bin/fauxshell-host --files");
    } else if (g_strcmp0(action, "launcher") == 0) {
        spawn_command("/run/current-system/sw/bin/fauxshell-host --launcher-toggle");
    } else {
        g_warning("unknown fauxshell action: %s", action);
    }
}

static void action_clicked(GtkButton *button, gpointer user_data) {
    App *app = (App *)user_data;
    const char *action = (const char *)g_object_get_data(G_OBJECT(button), "action");
    const char *label = gtk_button_get_label(button);
    if (action == NULL) {
        return;
    }
    if (g_str_has_prefix(action, "nav:")) {
        handle_shell_event(app, action);
        return;
    }
    if (g_str_has_prefix(action, "zoom:")) {
        app_handle_zoom_action(app, action);
        return;
    }
    if (g_str_has_prefix(action, "clipboard:")) {
        app_handle_clipboard_action(app, action);
        return;
    }
    run_action(action);
    if (label != NULL) {
        char *first_line = g_strdup(label);
        char *newline = strchr(first_line, '\n');
        if (newline != NULL) {
            *newline = '\0';
        }
        char *status = g_strdup_printf("Opened %s", first_line);
        set_status(app, status);
        g_free(first_line);
        g_free(status);
    }
}

static GtkWidget *make_button(App *app, const char *label, const char *action) {
    GtkWidget *button = gtk_button_new_with_label(label);
    gtk_widget_set_hexpand(button, TRUE);
    g_object_set_data_full(G_OBJECT(button), "action", g_strdup(action), g_free);
    g_signal_connect(button, "clicked", G_CALLBACK(action_clicked), app);
    return button;
}

static void set_button_action(GtkWidget *button, const char *action) {
    g_object_set_data_full(G_OBJECT(button), "action", g_strdup(action != NULL ? action : ""), g_free);
}

static void set_button_label_align(GtkWidget *button, float xalign) {
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(button));
    if (GTK_IS_LABEL(child)) {
        gtk_label_set_xalign(GTK_LABEL(child), xalign);
        gtk_label_set_line_wrap(GTK_LABEL(child), TRUE);
        gtk_label_set_lines(GTK_LABEL(child), 3);
        gtk_label_set_ellipsize(GTK_LABEL(child), PANGO_ELLIPSIZE_END);
    }
}

static GtkWidget *make_nav_button(App *app, const char *label, const char *action) {
    GtkWidget *button = make_button(app, label, action);
    gtk_widget_set_hexpand(button, FALSE);
    return button;
}

static size_t curl_write_cb(char *ptr, size_t size, size_t nmemb, void *userdata) {
    Buffer *buffer = (Buffer *)userdata;
    size_t chunk = size * nmemb;
    char *next = g_realloc(buffer->data, buffer->size + chunk + 1);
    buffer->data = next;
    memcpy(buffer->data + buffer->size, ptr, chunk);
    buffer->size += chunk;
    buffer->data[buffer->size] = '\0';
    return chunk;
}

static gboolean fetch_json(const char *url, JsonParser **parser_out) {
    gboolean ok = FALSE;
    Buffer buffer = {0};
    CURL *curl = curl_easy_init();
    if (curl == NULL) {
        return FALSE;
    }

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 1400L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    CURLcode result = curl_easy_perform(curl);
    if (result == CURLE_OK && buffer.data != NULL) {
        JsonParser *parser = json_parser_new();
        GError *error = NULL;
        if (json_parser_load_from_data(parser, buffer.data, (gssize)buffer.size, &error)) {
            *parser_out = parser;
            ok = TRUE;
        } else {
            if (error != NULL) {
                g_warning("fauxshell json parse failed: %s", error->message);
                g_error_free(error);
            }
            g_object_unref(parser);
        }
    }

    curl_easy_cleanup(curl);
    g_free(buffer.data);
    return ok;
}

static gboolean post_json_timeout(const char *url, const char *payload, long timeout_ms, JsonParser **parser_out) {
    gboolean ok = FALSE;
    Buffer buffer = {0};
    CURL *curl = curl_easy_init();
    if (curl == NULL) {
        return FALSE;
    }

    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload != NULL ? payload : "{}");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, timeout_ms);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    CURLcode result = curl_easy_perform(curl);
    if (result == CURLE_OK && buffer.data != NULL) {
        long status = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
        JsonParser *parser = json_parser_new();
        GError *error = NULL;
        if (json_parser_load_from_data(parser, buffer.data, (gssize)buffer.size, &error)) {
            if (parser_out != NULL) {
                *parser_out = parser;
            } else {
                g_object_unref(parser);
            }
            ok = status >= 200 && status < 300;
        } else {
            if (error != NULL) {
                g_warning("fauxshell json parse failed: %s", error->message);
                g_error_free(error);
            }
            g_object_unref(parser);
        }
    }

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    g_free(buffer.data);
    return ok;
}

static gboolean post_json(const char *url, const char *payload, JsonParser **parser_out) {
    return post_json_timeout(url, payload, 1400L, parser_out);
}

static JsonObject *object_member(JsonObject *object, const char *key) {
    if (object == NULL || !json_object_has_member(object, key)) {
        return NULL;
    }
    JsonNode *node = json_object_get_member(object, key);
    if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node)) {
        return NULL;
    }
    return json_node_get_object(node);
}

static JsonArray *array_member(JsonObject *object, const char *key) {
    if (object == NULL || !json_object_has_member(object, key)) {
        return NULL;
    }
    JsonNode *node = json_object_get_member(object, key);
    if (node == NULL || !JSON_NODE_HOLDS_ARRAY(node)) {
        return NULL;
    }
    return json_node_get_array(node);
}

static const char *string_member(JsonObject *object, const char *key, const char *fallback) {
    if (object == NULL || !json_object_has_member(object, key)) {
        return fallback;
    }
    JsonNode *node = json_object_get_member(object, key);
    if (node == NULL || !JSON_NODE_HOLDS_VALUE(node)) {
        return fallback;
    }
    if (json_node_get_value_type(node) != G_TYPE_STRING) {
        return fallback;
    }
    const char *value = json_node_get_string(node);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

static double double_member(JsonObject *object, const char *key, double fallback) {
    if (object == NULL || !json_object_has_member(object, key)) {
        return fallback;
    }
    JsonNode *node = json_object_get_member(object, key);
    if (node == NULL || !JSON_NODE_HOLDS_VALUE(node)) {
        return fallback;
    }
    GType type = json_node_get_value_type(node);
    if (type == G_TYPE_DOUBLE || type == G_TYPE_INT64 || type == G_TYPE_INT) {
        return json_node_get_double(node);
    }
    return fallback;
}

static int int_member(JsonObject *object, const char *key, int fallback) {
    if (object == NULL || !json_object_has_member(object, key)) {
        return fallback;
    }
    JsonNode *node = json_object_get_member(object, key);
    if (node == NULL || !JSON_NODE_HOLDS_VALUE(node)) {
        return fallback;
    }
    GType type = json_node_get_value_type(node);
    if (type == G_TYPE_INT64 || type == G_TYPE_INT || type == G_TYPE_DOUBLE) {
        return (int)json_node_get_int(node);
    }
    return fallback;
}

static gboolean gauge_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    (void)user_data;
    GaugeData *data = (GaugeData *)g_object_get_data(G_OBJECT(widget), "gauge-data");
    if (data == NULL) {
        return FALSE;
    }

    int width = gtk_widget_get_allocated_width(widget);
    int height = gtk_widget_get_allocated_height(widget);
    double cx = width / 2.0;
    double cy = height / 2.0;
    double size = MIN(width, height);
    double radius = size / 2.0 - 5.0;
    double value = CLAMP(data->value, 0.0, 100.0);

    cairo_set_line_width(cr, 4.5);
    cairo_set_source_rgba(cr, 0.18, 0.20, 0.22, 1.0);
    cairo_arc(cr, cx, cy, radius, 0, 2.0 * G_PI);
    cairo_stroke(cr);

    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
    cairo_set_source_rgba(cr, data->color.red, data->color.green, data->color.blue, 1.0);
    cairo_arc(cr, cx, cy, radius, -G_PI / 2.0, -G_PI / 2.0 + (2.0 * G_PI * value / 100.0));
    cairo_stroke(cr);

    char pct[16];
    g_snprintf(pct, sizeof(pct), "%.0f%%", value);

    cairo_select_font_face(cr, "Sans", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
    cairo_set_source_rgba(cr, 0.94, 0.95, 0.93, 1.0);
    cairo_set_font_size(cr, 7.5);
    cairo_text_extents_t extents;
    cairo_text_extents(cr, data->title, &extents);
    cairo_move_to(cr, cx - extents.width / 2.0 - extents.x_bearing, cy - 2.0);
    cairo_show_text(cr, data->title);

    cairo_select_font_face(cr, "Sans", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
    cairo_set_source_rgba(cr, 0.64, 0.67, 0.70, 1.0);
    cairo_set_font_size(cr, 7.0);
    cairo_text_extents(cr, pct, &extents);
    cairo_move_to(cr, cx - extents.width / 2.0 - extents.x_bearing, cy + 9.0);
    cairo_show_text(cr, pct);
    return FALSE;
}

static GtkWidget *make_gauge(const char *title, const char *color) {
    GtkWidget *area = gtk_drawing_area_new();
    GaugeData *data = g_new0(GaugeData, 1);
    g_strlcpy(data->title, title, sizeof(data->title));
    data->value = 0.0;
    gdk_rgba_parse(&data->color, color);
    gtk_widget_set_size_request(area, 50, 50);
    g_object_set_data_full(G_OBJECT(area), "gauge-data", data, g_free);
    g_signal_connect(area, "draw", G_CALLBACK(gauge_draw), NULL);
    return area;
}

static void set_gauge(GtkWidget *gauge, double value) {
    GaugeData *data = (GaugeData *)g_object_get_data(G_OBJECT(gauge), "gauge-data");
    if (data != NULL) {
        data->value = CLAMP(value, 0.0, 100.0);
        gtk_widget_queue_draw(gauge);
    }
}

static GtkWidget *make_label(const char *text, const char *class_name, float xalign) {
    GtkWidget *label = gtk_label_new(text);
    gtk_label_set_xalign(GTK_LABEL(label), xalign);
    gtk_label_set_yalign(GTK_LABEL(label), 0.5);
    gtk_label_set_line_wrap(GTK_LABEL(label), TRUE);
    gtk_label_set_ellipsize(GTK_LABEL(label), PANGO_ELLIPSIZE_END);
    if (class_name != NULL) {
        add_class(label, class_name);
    }
    return label;
}

static GtkWidget *make_card(const char *title) {
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 10);
    add_class(box, "card");
    gtk_widget_set_hexpand(box, TRUE);
    gtk_widget_set_vexpand(box, TRUE);
    if (title != NULL && title[0] != '\0') {
        GtkWidget *label = make_label(title, "card-title", 0.0f);
        gtk_box_pack_start(GTK_BOX(box), label, FALSE, FALSE, 0);
    }
    return box;
}

static void update_calendar(App *app) {
    time_t now = time(NULL);
    struct tm current = *localtime(&now);
    char title[64];
    strftime(title, sizeof(title), "%B %Y", &current);
    set_label(app->calendar_title, title);

    GList *children = gtk_container_get_children(GTK_CONTAINER(app->calendar_grid));
    for (GList *item = children; item != NULL; item = item->next) {
        gtk_widget_destroy(GTK_WIDGET(item->data));
    }
    g_list_free(children);

    const char *days[] = {"S", "M", "T", "W", "T", "F", "S"};
    for (int col = 0; col < 7; col++) {
        GtkWidget *day = make_label(days[col], "calendar-head", 0.5f);
        gtk_grid_attach(GTK_GRID(app->calendar_grid), day, col, 0, 1, 1);
    }

    struct tm first = current;
    first.tm_mday = 1;
    mktime(&first);
    int start = first.tm_wday;
    int month = current.tm_mon;
    int year = current.tm_year;
    int days_in_month = 31;
    for (int day = 29; day <= 31; day++) {
        struct tm probe = first;
        probe.tm_mday = day;
        mktime(&probe);
        if (probe.tm_mon != month) {
            days_in_month = day - 1;
            break;
        }
    }

    int row = 1;
    int col = start;
    for (int day = 1; day <= days_in_month; day++) {
        char text[4];
        g_snprintf(text, sizeof(text), "%d", day);
        GtkWidget *label = make_label(text, "calendar-day", 0.5f);
        if (day == current.tm_mday && month == current.tm_mon && year == current.tm_year) {
            add_class(label, "today");
        }
        gtk_grid_attach(GTK_GRID(app->calendar_grid), label, col, row, 1, 1);
        col++;
        if (col == 7) {
            col = 0;
            row++;
        }
    }
    gtk_widget_show_all(app->calendar_grid);
}

static gboolean update_clock(gpointer user_data) {
    App *app = (App *)user_data;
    time_t now = time(NULL);
    struct tm local = *localtime(&now);
    const char *part = "evening";
    if (local.tm_hour < 12) {
        part = "morning";
    } else if (local.tm_hour < 18) {
        part = "afternoon";
    }

    char *greeting = g_strdup_printf("Good %s, %s.", part, app->user != NULL ? app->user : "chvk");
    set_label(app->greeting, greeting);
    g_free(greeting);

    char clock_text[96];
    strftime(clock_text, sizeof(clock_text), "%A, %B %e at %l:%M %p", &local);
    set_label(app->clock_line, clock_text);
    return G_SOURCE_CONTINUE;
}

static char *row_text(JsonObject *row, const char *fallback) {
    const char *title = string_member(row, "title", fallback);
    int updated_at = int_member(row, "updated_at", 0);
    if (updated_at <= 0) {
        return g_strdup(title);
    }
    time_t stamp = (time_t)updated_at;
    struct tm local = *localtime(&stamp);
    char when[32];
    strftime(when, sizeof(when), "%a %H:%M", &local);
    return g_strdup_printf("%s  -  %s", title, when);
}

static char *bubble_text(JsonObject *row, const char *fallback) {
    const char *title = string_member(row, "title", fallback);
    const char *source = string_member(row, "source", "context");
    const char *kind = string_member(row, "kind", "");
    const char *text = string_member(row, "text", "");
    int updated_at = int_member(row, "updated_at", 0);
    char when[32] = "";
    if (updated_at > 0) {
        time_t stamp = (time_t)updated_at;
        struct tm local = *localtime(&stamp);
        strftime(when, sizeof(when), "%a %H:%M", &local);
    }

    char *meta = NULL;
    if (kind[0] != '\0' && g_strcmp0(kind, source) != 0) {
        meta = when[0] != '\0'
            ? g_strdup_printf("%s / %s  -  %s", source, kind, when)
            : g_strdup_printf("%s / %s", source, kind);
    } else {
        meta = when[0] != '\0'
            ? g_strdup_printf("%s  -  %s", source, when)
            : g_strdup(source);
    }

    char *result = NULL;
    if (text[0] != '\0') {
        result = g_strdup_printf("%s\n%s\n%s", title, meta, text);
    } else {
        result = g_strdup_printf("%s\n%s", title, meta);
    }
    g_free(meta);
    return result;
}

static void update_row_buttons(GtkWidget **rows, JsonArray *array, const char *fallback) {
    guint count = array != NULL ? json_array_get_length(array) : 0;
    for (guint i = 0; i < MAX_ROWS; i++) {
        if (i < count) {
            JsonObject *row = json_array_get_object_element(array, i);
            char *text = row_text(row, fallback);
            gtk_button_set_label(GTK_BUTTON(rows[i]), text);
            gtk_widget_set_sensitive(rows[i], TRUE);
            gtk_widget_show(rows[i]);
            g_free(text);
        } else {
            gtk_button_set_label(GTK_BUTTON(rows[i]), i == 0 ? fallback : "");
            gtk_widget_set_sensitive(rows[i], i == 0);
            if (i == 0) {
                gtk_widget_show(rows[i]);
            } else {
                gtk_widget_hide(rows[i]);
            }
        }
    }
}

static char *format_file_size(int size) {
    if (size >= 1024 * 1024) {
        return g_strdup_printf("%.1f MB", size / (1024.0 * 1024.0));
    }
    if (size >= 1024) {
        return g_strdup_printf("%.1f KB", size / 1024.0);
    }
    return g_strdup_printf("%d B", MAX(size, 0));
}

static char *file_row_text(JsonObject *row, const char *fallback) {
    const char *title = string_member(row, "title", fallback);
    const char *root = string_member(row, "root", "Files");
    const char *kind = string_member(row, "kind", "file");
    int size = int_member(row, "size", 0);
    int updated_at = int_member(row, "updated_at", 0);
    char when[32] = "";
    if (updated_at > 0) {
        time_t stamp = (time_t)updated_at;
        struct tm local = *localtime(&stamp);
        strftime(when, sizeof(when), "%a %H:%M", &local);
    }
    char *size_text = format_file_size(size);
    char *meta = NULL;
    if (when[0] != '\0') {
        meta = g_strdup_printf("%s / %s  -  %s  -  %s", root, kind, when, size_text);
    } else {
        meta = g_strdup_printf("%s / %s  -  %s", root, kind, size_text);
    }
    char *result = g_strdup_printf("%s\n%s", title, meta);
    g_free(meta);
    g_free(size_text);
    return result;
}

static void update_file_rows(App *app, JsonArray *array) {
    guint count = array != NULL ? json_array_get_length(array) : 0;
    for (guint i = 0; i < FILE_ROWS; i++) {
        if (app->file_rows[i] == NULL) {
            continue;
        }
        if (i < count) {
            JsonObject *row = json_array_get_object_element(array, i);
            char *text = file_row_text(row, "Recent file");
            set_label(app->file_rows[i], text);
            gtk_widget_show(app->file_rows[i]);
            g_free(text);
        } else {
            set_label(app->file_rows[i], i == 0 ? "No recent files in watched roots yet." : "");
            if (i == 0) {
                gtk_widget_show(app->file_rows[i]);
            } else {
                gtk_widget_hide(app->file_rows[i]);
            }
        }
    }
}

static gboolean desktop_scroll_event(GtkWidget *widget, GdkEventScroll *event, gpointer user_data) {
    (void)widget;
    App *app = (App *)user_data;
    if (event == NULL || (event->state & GDK_CONTROL_MASK) == 0) {
        return FALSE;
    }

    double delta = 0.0;
    if (event->direction == GDK_SCROLL_SMOOTH) {
        delta = event->delta_y;
    } else if (event->direction == GDK_SCROLL_UP) {
        delta = -1.0;
    } else if (event->direction == GDK_SCROLL_DOWN) {
        delta = 1.0;
    }

    if (fabs(delta) < 0.01) {
        return TRUE;
    }

    double current = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    double factor = delta < 0.0 ? DESKTOP_ZOOM_STEP : (1.0 / DESKTOP_ZOOM_STEP);
    app_set_desktop_zoom(app, current * factor, event->x, event->y);
    return TRUE;
}

static gboolean desktop_event(GtkWidget *widget, GdkEvent *event, gpointer user_data) {
    (void)widget;
    App *app = (App *)user_data;
    if (event == NULL) {
        return FALSE;
    }
#if GTK_CHECK_VERSION(3, 18, 0)
    if (event->type == GDK_TOUCHPAD_PINCH) {
        if (event->touchpad_pinch.phase == GDK_TOUCHPAD_GESTURE_PHASE_BEGIN) {
            app->pinch_base_zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
            return TRUE;
        }
        if (event->touchpad_pinch.phase == GDK_TOUCHPAD_GESTURE_PHASE_UPDATE) {
            double scale = event->touchpad_pinch.scale;
            if (scale > 0.05) {
                app_set_desktop_zoom(
                    app,
                    app->pinch_base_zoom * scale,
                    event->touchpad_pinch.x,
                    event->touchpad_pinch.y
                );
            }
            return TRUE;
        }
        if (event->touchpad_pinch.phase == GDK_TOUCHPAD_GESTURE_PHASE_END ||
            event->touchpad_pinch.phase == GDK_TOUCHPAD_GESTURE_PHASE_CANCEL) {
            app->pinch_base_zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
            return TRUE;
        }
    }
#endif
    return FALSE;
}

static gboolean map_connections_draw(GtkWidget *widget, cairo_t *cr, gpointer user_data) {
    (void)widget;
    App *app = (App *)user_data;
    double zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;

    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
    cairo_set_line_join(cr, CAIRO_LINE_JOIN_ROUND);

    cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.035);
    cairo_set_line_width(cr, 1.0);
    double grid = 140.0 * zoom;
    if (grid >= 36.0) {
        for (double x = 0.0; x <= MAP_WIDTH * zoom; x += grid) {
            cairo_move_to(cr, x, 0.0);
            cairo_line_to(cr, x, MAP_HEIGHT * zoom);
        }
        for (double y = 0.0; y <= MAP_HEIGHT * zoom; y += grid) {
            cairo_move_to(cr, 0.0, y);
            cairo_line_to(cr, MAP_WIDTH * zoom, y);
        }
        cairo_stroke(cr);
    }

    for (int i = 0; i < MAP_EDGE_COUNT; i++) {
        MapEdge *edge = &app->edges[i];
        if (!edge->active) {
            continue;
        }
        MapNode *from = &app->nodes[edge->from];
        MapNode *to = &app->nodes[edge->to];
        if (from->widget == NULL || to->widget == NULL) {
            continue;
        }

        double x1 = (from->x + from->width / 2.0) * zoom;
        double y1 = (from->y + from->height / 2.0) * zoom;
        double x2 = (to->x + to->width / 2.0) * zoom;
        double y2 = (to->y + to->height / 2.0) * zoom;
        double dx = fabs(x2 - x1);
        double bend = MAX(70.0 * zoom, dx * 0.32);

        cairo_set_source_rgba(cr, 0.0, 0.78, 1.0, 0.36);
        cairo_set_line_width(cr, MAX(1.4, 2.4 * zoom));
        cairo_move_to(cr, x1, y1);
        cairo_curve_to(cr, x1 + bend, y1, x2 - bend, y2, x2, y2);
        cairo_stroke(cr);

        cairo_set_source_rgba(cr, 1.0, 0.47, 0.0, 0.72);
        cairo_arc(cr, x1, y1, MAX(3.0, 4.0 * zoom), 0, 2.0 * G_PI);
        cairo_fill(cr);
        cairo_set_source_rgba(cr, 0.0, 0.78, 1.0, 0.82);
        cairo_arc(cr, x2, y2, MAX(3.0, 4.0 * zoom), 0, 2.0 * G_PI);
        cairo_fill(cr);
    }

    if (app_overview_mode(app)) {
        for (int i = 0; i < MAP_NODE_COUNT; i++) {
            MapNode *node = &app->nodes[i];
            if (node->id == NULL) {
                continue;
            }
            double x = node->x * zoom;
            double y = node->y * zoom;
            double width = node->width * zoom;
            double height = node->height * zoom;
            double radius = MAX(5.0, 8.0 * zoom);

            cairo_new_sub_path(cr);
            cairo_arc(cr, x + width - radius, y + radius, radius, -G_PI / 2.0, 0.0);
            cairo_arc(cr, x + width - radius, y + height - radius, radius, 0.0, G_PI / 2.0);
            cairo_arc(cr, x + radius, y + height - radius, radius, G_PI / 2.0, G_PI);
            cairo_arc(cr, x + radius, y + radius, radius, G_PI, 3.0 * G_PI / 2.0);
            cairo_close_path(cr);
            cairo_set_source_rgba(cr, 0.08, 0.09, 0.10, 0.92);
            cairo_fill_preserve(cr);
            cairo_set_source_rgba(cr, 1.0, 0.47, 0.0, 0.56);
            cairo_set_line_width(cr, MAX(1.0, 1.8 * zoom));
            cairo_stroke(cr);

            cairo_select_font_face(cr, "Sans", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
            cairo_set_font_size(cr, CLAMP(16.0 * zoom, 7.0, 22.0));
            cairo_set_source_rgba(cr, 0.94, 0.95, 0.93, 0.95);
            const char *title = node->title != NULL ? node->title : node->id;
            cairo_move_to(cr, x + (16.0 * zoom), y + (30.0 * zoom));
            cairo_show_text(cr, title);

            cairo_select_font_face(cr, "Sans", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
            cairo_set_font_size(cr, CLAMP(11.0 * zoom, 6.0, 14.0));
            cairo_set_source_rgba(cr, 0.0, 0.78, 1.0, 0.82);
            cairo_move_to(cr, x + (16.0 * zoom), y + (50.0 * zoom));
            cairo_show_text(cr, node->id);
        }
    }

    return FALSE;
}

static gboolean map_node_button_press(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    App *app = (App *)user_data;
    if (event == NULL || event->button != 1) {
        return FALSE;
    }
    int index = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(widget), "map-node-index"));
    if (index < 0 || index >= MAP_NODE_COUNT) {
        return FALSE;
    }
    app->drag_node = index;
    app->drag_start_root_x = event->x_root;
    app->drag_start_root_y = event->y_root;
    app->drag_start_x = app->nodes[index].x;
    app->drag_start_y = app->nodes[index].y;
    gtk_grab_add(widget);
    return FALSE;
}

static gboolean map_node_motion(GtkWidget *widget, GdkEventMotion *event, gpointer user_data) {
    (void)widget;
    App *app = (App *)user_data;
    if (event == NULL || app->drag_node < 0 || app->drag_node >= MAP_NODE_COUNT) {
        return FALSE;
    }
    double zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    MapNode *node = &app->nodes[app->drag_node];
    int next_x = app->drag_start_x + (int)round((event->x_root - app->drag_start_root_x) / zoom);
    int next_y = app->drag_start_y + (int)round((event->y_root - app->drag_start_root_y) / zoom);
    node->x = CLAMP(next_x, 0, MAP_WIDTH - node->width);
    node->y = CLAMP(next_y, 0, MAP_HEIGHT - node->height);
    app_layout_map(app);
    return TRUE;
}

static gboolean map_node_button_release(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    App *app = (App *)user_data;
    if (event == NULL || event->button != 1 || app->drag_node < 0) {
        return FALSE;
    }
    gtk_grab_remove(widget);
    app->drag_node = -1;
    app_save_map_positions(app);
    set_status(app, "Continuity map updated");
    return FALSE;
}

static int map_hit_test(App *app, double x, double y) {
    if (app == NULL) {
        return -1;
    }
    double zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    double map_x = x / zoom;
    double map_y = y / zoom;
    for (int i = MAP_NODE_COUNT - 1; i >= 0; i--) {
        MapNode *node = &app->nodes[i];
        if (node->id == NULL) {
            continue;
        }
        if (map_x >= node->x && map_x <= node->x + node->width &&
            map_y >= node->y && map_y <= node->y + node->height) {
            return i;
        }
    }
    return -1;
}

static gboolean map_canvas_button_press(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    App *app = (App *)user_data;
    if (event == NULL || event->button != 1 || !app_overview_mode(app)) {
        return FALSE;
    }
    int index = map_hit_test(app, event->x, event->y);
    if (index < 0) {
        return FALSE;
    }
    app->drag_node = index;
    app->drag_start_root_x = event->x_root;
    app->drag_start_root_y = event->y_root;
    app->drag_start_x = app->nodes[index].x;
    app->drag_start_y = app->nodes[index].y;
    gtk_grab_add(widget);
    return TRUE;
}

static gboolean map_canvas_motion(GtkWidget *widget, GdkEventMotion *event, gpointer user_data) {
    (void)widget;
    App *app = (App *)user_data;
    if (event == NULL || app->drag_node < 0 || app->drag_node >= MAP_NODE_COUNT || !app_overview_mode(app)) {
        return FALSE;
    }
    double zoom = app->desktop_zoom > 0.0 ? app->desktop_zoom : 1.0;
    MapNode *node = &app->nodes[app->drag_node];
    int next_x = app->drag_start_x + (int)round((event->x_root - app->drag_start_root_x) / zoom);
    int next_y = app->drag_start_y + (int)round((event->y_root - app->drag_start_root_y) / zoom);
    node->x = CLAMP(next_x, 0, MAP_WIDTH - node->width);
    node->y = CLAMP(next_y, 0, MAP_HEIGHT - node->height);
    app_layout_map(app);
    return TRUE;
}

static gboolean map_canvas_button_release(GtkWidget *widget, GdkEventButton *event, gpointer user_data) {
    App *app = (App *)user_data;
    if (event == NULL || event->button != 1 || app->drag_node < 0 || !app_overview_mode(app)) {
        return FALSE;
    }
    gtk_grab_remove(widget);
    app->drag_node = -1;
    app_save_map_positions(app);
    set_status(app, "Continuity map updated");
    return TRUE;
}

static GtkWidget *map_wrap_card(App *app, MapNodeId id, GtkWidget *card, const char *node_id, const char *title, int x, int y, int width, int height) {
    GtkWidget *event_box = gtk_event_box_new();
    gtk_event_box_set_visible_window(GTK_EVENT_BOX(event_box), FALSE);
    gtk_widget_add_events(
        event_box,
        GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK | GDK_POINTER_MOTION_MASK | GDK_SCROLL_MASK | GDK_SMOOTH_SCROLL_MASK
    );
    g_object_set_data(G_OBJECT(event_box), "map-node-index", GINT_TO_POINTER((int)id));
    g_signal_connect(event_box, "button-press-event", G_CALLBACK(map_node_button_press), app);
    g_signal_connect(event_box, "motion-notify-event", G_CALLBACK(map_node_motion), app);
    g_signal_connect(event_box, "button-release-event", G_CALLBACK(map_node_button_release), app);

    gtk_container_add(GTK_CONTAINER(event_box), card);
    app->nodes[id].id = node_id;
    app->nodes[id].title = title;
    app->nodes[id].widget = event_box;
    app->nodes[id].x = x;
    app->nodes[id].y = y;
    app->nodes[id].width = width;
    app->nodes[id].height = height;
    return event_box;
}

static void app_init_map(App *app) {
    app->desktop_zoom = 1.0;
    app->pinch_base_zoom = 1.0;
    app->drag_node = -1;
    app->edges[EDGE_HERO_CONTINUITY] = (MapEdge){NODE_HERO, NODE_CONTINUITY, "current work", TRUE};
    app->edges[EDGE_CONTINUITY_NOTES] = (MapEdge){NODE_CONTINUITY, NODE_NOTES, "notes", TRUE};
    app->edges[EDGE_CONTINUITY_APPS] = (MapEdge){NODE_CONTINUITY, NODE_APPS, "threads", TRUE};
    app->edges[EDGE_CONTINUITY_TELEMETRY] = (MapEdge){NODE_CONTINUITY, NODE_TELEMETRY, "machine state", TRUE};
    app->edges[EDGE_CONTINUITY_FILES] = (MapEdge){NODE_CONTINUITY, NODE_FILES, "file evidence", TRUE};
    app->edges[EDGE_FILES_NOTES] = (MapEdge){NODE_FILES, NODE_NOTES, "captures", TRUE};
    app->edges[EDGE_WEATHER_CALENDAR] = (MapEdge){NODE_WEATHER, NODE_CALENDAR, "day context", TRUE};
    app->edges[EDGE_APPS_TELEMETRY] = (MapEdge){NODE_APPS, NODE_TELEMETRY, "runtime", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_FENNIX] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_FENNIX, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_FAUXNIX] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_FAUXNIX, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_FAUXDEX] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_FAUXDEX, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_COWRITER] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_COWRITER, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_ADMIN] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_ADMIN, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_ROOT] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_ROOT, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_WEB] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_WEB, "thread", TRUE};
    app->edges[EDGE_CONTINUITY_THREAD_TERMINAL] = (MapEdge){NODE_CONTINUITY, NODE_THREAD_TERMINAL, "thread", TRUE};
}

static void update_continuity_buttons(GtkWidget **rows, JsonArray *array, const char *fallback) {
    guint count = array != NULL ? json_array_get_length(array) : 0;
    for (guint i = 0; i < CONTINUITY_ROWS; i++) {
        if (i < count) {
            JsonObject *row = json_array_get_object_element(array, i);
            char *text = bubble_text(row, fallback);
            gtk_button_set_label(GTK_BUTTON(rows[i]), text);
            set_button_action(rows[i], string_member(row, "action", "thread:fennix"));
            gtk_widget_set_sensitive(rows[i], TRUE);
            gtk_widget_show(rows[i]);
            g_free(text);
        } else {
            gtk_button_set_label(GTK_BUTTON(rows[i]), i == 0 ? fallback : "");
            set_button_action(rows[i], "thread:fennix");
            gtk_widget_set_sensitive(rows[i], i == 0);
            if (i == 0) {
                gtk_widget_show(rows[i]);
            } else {
                gtk_widget_hide(rows[i]);
            }
        }
    }
}

static gboolean update_summary(gpointer user_data) {
    App *app = (App *)user_data;
    JsonParser *parser = NULL;
    if (!fetch_json(API_BASE "/summary", &parser)) {
        set_status(app, "Fauxd is starting or offline");
        set_label(app->net_state, "fauxd offline");
        return G_SOURCE_CONTINUE;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root == NULL || !JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return G_SOURCE_CONTINUE;
    }
    JsonObject *summary = json_node_get_object(root);
    const char *user = string_member(summary, "user", NULL);
    if (user != NULL && user[0] != '\0' && g_strcmp0(user, app->user) != 0) {
        g_free(app->user);
        app->user = g_strdup(user);
        update_clock(app);
    }

    JsonObject *weather = object_member(summary, "weather");
    set_label(app->weather_symbol, string_member(weather, "symbol", "--"));
    set_label(app->weather_summary, string_member(weather, "summary", "Set weather location"));
    const char *location = string_member(weather, "location", "");
    char *location_text = location[0] != '\0'
        ? g_strdup_printf("Location: %s", location)
        : g_strdup("Ask Fennix to set weather");
    set_label(app->weather_location, location_text);
    g_free(location_text);

    JsonObject *telemetry = object_member(summary, "telemetry");
    double cpu = double_member(telemetry, "cpu_percent", 0.0);
    double ram = double_member(telemetry, "memory_percent", 0.0);
    double load = double_member(telemetry, "load_percent", 0.0);
    double battery = double_member(telemetry, "battery_percent", 0.0);
    set_gauge(app->cpu_gauge, cpu);
    set_gauge(app->ram_gauge, ram);
    set_gauge(app->load_gauge, load);
    set_gauge(app->battery_gauge, battery);
    set_label(app->net_state, string_member(telemetry, "network_text", "n/a"));
    set_label(app->audio_state, string_member(telemetry, "audio_text", "n/a"));
    set_label(app->power_state, string_member(telemetry, "battery_text", "n/a"));
    const char *memory_text = string_member(telemetry, "memory_text", "RAM n/a");
    char *telemetry_detail = g_strdup_printf("%s   CPU %.0f%%   Load %.0f%%", memory_text, cpu, load);
    set_label(app->telemetry_detail, telemetry_detail);
    g_free(telemetry_detail);

    JsonObject *continuity = object_member(summary, "continuity");
    int continuity_count = int_member(continuity, "count", 0);
    update_continuity_buttons(
        app->continuity_rows,
        array_member(continuity, "bubbles"),
        "Continuity gathers here as Fennix, notes, threads, and git snapshots accumulate."
    );

    JsonObject *notes = object_member(summary, "notes");
    int note_count = int_member(notes, "count", 0);
    JsonObject *clipboard = object_member(summary, "clipboard");
    int clip_count = int_member(clipboard, "count", 0);
    char *notes_summary = g_strdup_printf(
        "%d note%s / %d clipboard capture%s",
        note_count,
        note_count == 1 ? "" : "s",
        clip_count,
        clip_count == 1 ? "" : "s"
    );
    set_label(app->notes_summary, notes_summary);
    g_free(notes_summary);
    update_row_buttons(app->note_rows, array_member(notes, "recent"), "Open notes and clipboard");
    JsonObject *files = object_member(summary, "files");
    int file_count = int_member(files, "count", 0);
    int files_scanned = int_member(files, "scanned", 0);
    char *file_summary = g_strdup_printf(
        "%d recent candidate%s / %d scanned",
        file_count,
        file_count == 1 ? "" : "s",
        files_scanned
    );
    set_label(app->file_summary, file_summary);
    g_free(file_summary);
    update_file_rows(app, array_member(files, "recent"));
    JsonObject *thread_cards = object_member(summary, "thread_cards");
    update_thread_cards(app, array_member(thread_cards, "recent"));
    app->edges[EDGE_HERO_CONTINUITY].active = continuity_count > 0;
    app->edges[EDGE_CONTINUITY_NOTES].active = note_count > 0 || clip_count > 0;
    app->edges[EDGE_CONTINUITY_FILES].active = file_count > 0;
    app->edges[EDGE_FILES_NOTES].active = file_count > 0 && (note_count > 0 || clip_count > 0);
    app->edges[EDGE_CONTINUITY_APPS].active = TRUE;
    app->edges[EDGE_CONTINUITY_TELEMETRY].active = TRUE;
    app->edges[EDGE_WEATHER_CALENDAR].active = TRUE;
    app->edges[EDGE_APPS_TELEMETRY].active = TRUE;
    if (app->connection_layer != NULL) {
        gtk_widget_queue_draw(app->connection_layer);
    }

    set_status(app, "Native Sway desktop ready");
    g_object_unref(parser);
    return G_SOURCE_CONTINUE;
}

static void handle_shell_event(App *app, const char *event) {
    if (g_strcmp0(event, "nav:home") == 0) {
        app_handle_zoom_action(app, "zoom:reset");
        if (app->desktop_scroll != NULL) {
            GtkAdjustment *hadj = gtk_scrolled_window_get_hadjustment(GTK_SCROLLED_WINDOW(app->desktop_scroll));
            GtkAdjustment *vadj = gtk_scrolled_window_get_vadjustment(GTK_SCROLLED_WINDOW(app->desktop_scroll));
            if (hadj != NULL) {
                gtk_adjustment_set_value(hadj, gtk_adjustment_get_lower(hadj));
            }
            if (vadj != NULL) {
                gtk_adjustment_set_value(vadj, gtk_adjustment_get_lower(vadj));
            }
        }
        set_status(app, "Home");
    } else if (g_strcmp0(event, "nav:threads") == 0) {
        run_action("threads:menu");
        set_status(app, "Opened threads");
    } else if (g_strcmp0(event, "nav:back") == 0) {
        set_status(app, "Back gesture reserved");
    } else if (g_strcmp0(event, "nav:forward") == 0) {
        set_status(app, "Forward gesture reserved");
    } else if (g_strcmp0(event, "zoom:in") == 0 || g_strcmp0(event, "zoom:out") == 0 || g_strcmp0(event, "zoom:reset") == 0) {
        app_handle_zoom_action(app, event);
    }
}

static gboolean update_events(gpointer user_data) {
    App *app = (App *)user_data;
    char *url = g_strdup_printf(API_BASE "/events?since=%d", app->last_event_id);
    JsonParser *parser = NULL;
    gboolean ok = fetch_json(url, &parser);
    g_free(url);
    if (!ok) {
        return G_SOURCE_CONTINUE;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root != NULL && JSON_NODE_HOLDS_OBJECT(root)) {
        JsonObject *object = json_node_get_object(root);
        JsonArray *events = array_member(object, "events");
        if (events != NULL) {
            guint count = json_array_get_length(events);
            for (guint i = 0; i < count; i++) {
                JsonObject *event = json_array_get_object_element(events, i);
                int id = int_member(event, "id", app->last_event_id);
                if (id > app->last_event_id) {
                    app->last_event_id = id;
                }
                JsonObject *payload = object_member(event, "payload");
                handle_shell_event(app, string_member(payload, "event", ""));
            }
        }
    }
    g_object_unref(parser);
    return G_SOURCE_CONTINUE;
}

static GtkWidget *make_status_row(const char *name, GtkWidget **value_out) {
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    GtkWidget *label = make_label(name, "muted", 0.0f);
    GtkWidget *value = make_label("checking", "strong", 1.0f);
    gtk_widget_set_hexpand(value, TRUE);
    gtk_box_pack_start(GTK_BOX(row), label, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), value, TRUE, TRUE, 0);
    *value_out = value;
    return row;
}

static GtkWidget *make_thread_card(App *app, int index, const char *title, const char *description, const char *action) {
    GtkWidget *card = make_card(title);
    app->thread_meta[index] = make_label(description, "small-muted", 0.0f);
    app->thread_activity[index] = make_label("Thread memory will appear here as this workspace is used.", "thread-activity", 0.0f);
    gtk_widget_set_size_request(app->thread_activity[index], -1, 82);
    GtkWidget *open = make_button(app, "Open Thread", action);
    add_class(open, "row-button");
    gtk_box_pack_start(GTK_BOX(card), app->thread_meta[index], FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(card), app->thread_activity[index], TRUE, TRUE, 0);
    gtk_box_pack_end(GTK_BOX(card), open, FALSE, FALSE, 0);
    return card;
}

static void update_thread_cards(App *app, JsonArray *array) {
    guint count = array != NULL ? json_array_get_length(array) : 0;
    for (guint i = 0; i < THREAD_CARD_COUNT; i++) {
        if (app->thread_meta[i] == NULL || app->thread_activity[i] == NULL) {
            continue;
        }
        if (i >= count) {
            set_label(app->thread_meta[i], "Thread activity unavailable");
            set_label(app->thread_activity[i], "Open this thread to begin collecting context.");
            continue;
        }
        JsonObject *thread = json_array_get_object_element(array, i);
        const char *description = string_member(thread, "description", "Thread workspace");
        const char *text = string_member(thread, "text", "Open this thread to begin collecting context.");
        int memories = int_member(thread, "memory_count", 0);
        int updated_at = int_member(thread, "updated_at", 0);
        char when[32] = "";
        if (updated_at > 0) {
            time_t stamp = (time_t)updated_at;
            struct tm local = *localtime(&stamp);
            strftime(when, sizeof(when), "%a %H:%M", &local);
        }
        char *meta = NULL;
        if (memories > 0 && when[0] != '\0') {
            meta = g_strdup_printf("%s  -  %d memor%s  -  %s", description, memories, memories == 1 ? "y" : "ies", when);
        } else if (when[0] != '\0') {
            meta = g_strdup_printf("%s  -  updated %s", description, when);
        } else {
            meta = g_strdup(description);
        }
        set_label(app->thread_meta[i], meta);
        set_label(app->thread_activity[i], text);
        g_free(meta);
    }
}

static GtkWidget *make_shell(App *app) {
    app_init_map(app);

    GtkWidget *main = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    add_class(main, "main");
    gtk_widget_set_hexpand(main, TRUE);
    gtk_widget_set_vexpand(main, TRUE);

    GtkWidget *nav = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    add_class(nav, "nav");
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "Back", "nav:back"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "Home", "nav:home"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "Forward", "nav:forward"), FALSE, FALSE, 0);
    app->status_line = make_label("Starting native desktop", "route-pill", 0.0f);
    gtk_widget_set_hexpand(app->status_line, TRUE);
    gtk_box_pack_start(GTK_BOX(nav), app->status_line, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "-", "zoom:out"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "100%", "zoom:reset"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "+", "zoom:in"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "Apps", "apps"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(nav), make_nav_button(app, "Fennix", "launcher"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(main), nav, FALSE, FALSE, 0);

    GtkWidget *scroll = gtk_scrolled_window_new(NULL, NULL);
    add_class(scroll, "desktop-scroll");
    app->desktop_scroll = scroll;
    gtk_widget_set_hexpand(scroll, TRUE);
    gtk_widget_set_vexpand(scroll, TRUE);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroll), GTK_POLICY_AUTOMATIC, GTK_POLICY_AUTOMATIC);
    gtk_scrolled_window_set_overlay_scrolling(GTK_SCROLLED_WINDOW(scroll), TRUE);
    gtk_scrolled_window_set_kinetic_scrolling(GTK_SCROLLED_WINDOW(scroll), TRUE);
    gtk_widget_add_events(scroll, GDK_SCROLL_MASK | GDK_SMOOTH_SCROLL_MASK);
#ifdef GDK_TOUCHPAD_GESTURE_MASK
    gtk_widget_add_events(scroll, GDK_TOUCHPAD_GESTURE_MASK);
#endif
    g_signal_connect(scroll, "scroll-event", G_CALLBACK(desktop_scroll_event), app);
    g_signal_connect(scroll, "event", G_CALLBACK(desktop_event), app);

    app->map_canvas = gtk_fixed_new();
    add_class(app->map_canvas, "card-map");
    gtk_widget_set_hexpand(app->map_canvas, TRUE);
    gtk_widget_set_vexpand(app->map_canvas, TRUE);
    gtk_widget_set_size_request(app->map_canvas, MAP_WIDTH, MAP_HEIGHT);

    app->connection_layer = gtk_drawing_area_new();
    add_class(app->connection_layer, "connection-layer");
    gtk_widget_set_size_request(app->connection_layer, MAP_WIDTH, MAP_HEIGHT);
    gtk_widget_add_events(
        app->connection_layer,
        GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK | GDK_POINTER_MOTION_MASK
    );
    g_signal_connect(app->connection_layer, "draw", G_CALLBACK(map_connections_draw), app);
    g_signal_connect(app->connection_layer, "button-press-event", G_CALLBACK(map_canvas_button_press), app);
    g_signal_connect(app->connection_layer, "motion-notify-event", G_CALLBACK(map_canvas_motion), app);
    g_signal_connect(app->connection_layer, "button-release-event", G_CALLBACK(map_canvas_button_release), app);
    gtk_fixed_put(GTK_FIXED(app->map_canvas), app->connection_layer, 0, 0);

    GtkWidget *hero = make_card(NULL);
    add_class(hero, "hero-card");
    GtkWidget *eyebrow = make_label("FauxnixOS", "eyebrow", 0.0f);
    app->greeting = make_label("Hello.", "hero-title", 0.0f);
    app->clock_line = make_label("Starting shell", "muted", 0.0f);
    GtkWidget *quick = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_pack_start(GTK_BOX(quick), make_button(app, "Web", "thread:web"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(quick), make_button(app, "Notes", "notes"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(quick), make_button(app, "Workspace", "thread:fauxnix"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(quick), make_button(app, "Cowriter", "thread:cowriter"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hero), eyebrow, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hero), app->greeting, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(hero), app->clock_line, FALSE, FALSE, 0);
    gtk_box_pack_end(GTK_BOX(hero), quick, FALSE, FALSE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_HERO, hero, "card:home", "Home", 80, 70, 780, 250),
        80,
        70
    );

    GtkWidget *weather = make_card("Weather");
    app->weather_symbol = make_label("--", "weather-symbol", 0.0f);
    app->weather_summary = make_label("Location awaits setup", "muted", 0.0f);
    app->weather_location = make_label("Ask Fennix to set weather", "small-muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(weather), app->weather_symbol, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(weather), app->weather_summary, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(weather), app->weather_location, FALSE, FALSE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_WEATHER, weather, "card:weather", "Weather", 950, 70, 340, 250),
        950,
        70
    );

    GtkWidget *calendar = make_card(NULL);
    app->calendar_title = make_label("Calendar", "card-title", 0.0f);
    app->calendar_grid = gtk_grid_new();
    gtk_grid_set_column_spacing(GTK_GRID(app->calendar_grid), 4);
    gtk_grid_set_row_spacing(GTK_GRID(app->calendar_grid), 4);
    gtk_grid_set_column_homogeneous(GTK_GRID(app->calendar_grid), TRUE);
    gtk_box_pack_start(GTK_BOX(calendar), app->calendar_title, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(calendar), app->calendar_grid, TRUE, TRUE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_CALENDAR, calendar, "card:calendar", "Calendar", 1360, 70, 340, 250),
        1360,
        70
    );

    GtkWidget *pickup = make_card("Continuity Constellation");
    for (int i = 0; i < CONTINUITY_ROWS; i++) {
        app->continuity_rows[i] = make_button(app, i == 0 ? "Fennix local assistant" : "", "thread:fennix");
        add_class(app->continuity_rows[i], "bubble-button");
        set_button_label_align(app->continuity_rows[i], 0.0f);
        gtk_box_pack_start(GTK_BOX(pickup), app->continuity_rows[i], FALSE, FALSE, 0);
    }
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_CONTINUITY, pickup, "card:continuity", "Continuity", 80, 390, 780, 720),
        80,
        390
    );

    GtkWidget *apps = make_card("Apps");
    GtkWidget *apps_grid = gtk_grid_new();
    gtk_grid_set_column_spacing(GTK_GRID(apps_grid), 8);
    gtk_grid_set_row_spacing(GTK_GRID(apps_grid), 8);
    const char *labels[] = {"Web", "Term", "Chat", "Write", "Admin", "Root", "Code", "Apps"};
    const char *actions[] = {"thread:web", "thread:terminal", "thread:fennix", "thread:cowriter", "thread:admin", "thread:root", "thread:fauxdex", "apps"};
    for (int i = 0; i < 8; i++) {
        gtk_grid_attach(GTK_GRID(apps_grid), make_button(app, labels[i], actions[i]), i % 2, i / 2, 1, 1);
    }
    gtk_box_pack_start(GTK_BOX(apps), apps_grid, TRUE, TRUE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_APPS, apps, "card:apps", "Apps", 950, 390, 340, 320),
        950,
        390
    );

    GtkWidget *notes = make_card("Notes / Clipboard");
    app->notes_summary = make_label("Checking notes", "muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(notes), app->notes_summary, FALSE, FALSE, 0);
    GtkWidget *clip_actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_pack_start(GTK_BOX(clip_actions), make_button(app, "Paste", "clipboard:paste"), TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(clip_actions), make_button(app, "Save", "clipboard:save"), TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(clip_actions), make_button(app, "Clear", "clipboard:clear"), TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(notes), clip_actions, FALSE, FALSE, 0);
    app->clipboard_preview = make_label("Clipboard empty. Copy text, press Paste, then Save.", "clipboard-preview", 0.0f);
    gtk_widget_set_size_request(app->clipboard_preview, -1, 62);
    gtk_box_pack_start(GTK_BOX(notes), app->clipboard_preview, FALSE, FALSE, 0);
    GtkWidget *recent_label = make_label("Recent Notes", "small-muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(notes), recent_label, FALSE, FALSE, 0);
    for (int i = 0; i < MAX_ROWS; i++) {
        app->note_rows[i] = make_button(app, i == 0 ? "Open notes and clipboard" : "", "notes");
        add_class(app->note_rows[i], "row-button");
        gtk_box_pack_start(GTK_BOX(notes), app->note_rows[i], FALSE, FALSE, 0);
    }
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_NOTES, notes, "card:notes", "Notes / Clipboard", 1360, 390, 440, 720),
        1360,
        390
    );

    GtkWidget *files = make_card("Archivist Files");
    app->file_summary = make_label("Scanning watched roots", "muted", 0.0f);
    GtkWidget *file_scope = make_label("Watching Downloads - Pictures - Threads - Cowriter - Repos", "small-muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(files), app->file_summary, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(files), file_scope, FALSE, FALSE, 0);
    for (int i = 0; i < FILE_ROWS; i++) {
        app->file_rows[i] = make_label(i == 0 ? "Recent file evidence will appear here." : "", "file-row", 0.0f);
        gtk_widget_set_size_request(app->file_rows[i], -1, 46);
        gtk_box_pack_start(GTK_BOX(files), app->file_rows[i], FALSE, FALSE, 0);
    }
    GtkWidget *open_files = make_button(app, "Open Files", "files");
    add_class(open_files, "row-button");
    gtk_box_pack_end(GTK_BOX(files), open_files, FALSE, FALSE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_FILES, files, "card:files", "Archivist Files", 1360, 1140, 440, 390),
        1360,
        1140
    );

    GtkWidget *telemetry = make_card("Telemetry");
    GtkWidget *gauge_grid = gtk_grid_new();
    gtk_grid_set_column_spacing(GTK_GRID(gauge_grid), 8);
    gtk_grid_set_row_spacing(GTK_GRID(gauge_grid), 6);
    gtk_widget_set_halign(gauge_grid, GTK_ALIGN_CENTER);
    app->cpu_gauge = make_gauge("CPU", "#ff7800");
    app->ram_gauge = make_gauge("RAM", "#00c8ff");
    app->load_gauge = make_gauge("LOAD", "#74e0ad");
    app->battery_gauge = make_gauge("BAT", "#ff5aa5");
    gtk_grid_attach(GTK_GRID(gauge_grid), app->cpu_gauge, 0, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(gauge_grid), app->ram_gauge, 1, 0, 1, 1);
    gtk_grid_attach(GTK_GRID(gauge_grid), app->load_gauge, 0, 1, 1, 1);
    gtk_grid_attach(GTK_GRID(gauge_grid), app->battery_gauge, 1, 1, 1, 1);
    app->telemetry_detail = make_label("Waiting for Fauxd", "muted", 0.5f);
    gtk_box_pack_start(GTK_BOX(telemetry), gauge_grid, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(telemetry), app->telemetry_detail, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(telemetry), make_status_row("Net", &app->net_state), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(telemetry), make_status_row("Audio", &app->audio_state), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(telemetry), make_status_row("Power", &app->power_state), FALSE, FALSE, 0);
    gtk_fixed_put(
        GTK_FIXED(app->map_canvas),
        map_wrap_card(app, NODE_TELEMETRY, telemetry, "card:telemetry", "Telemetry", 950, 780, 340, 330),
        950,
        780
    );

    const MapNodeId thread_nodes[THREAD_CARD_COUNT] = {
        NODE_THREAD_FENNIX,
        NODE_THREAD_FAUXNIX,
        NODE_THREAD_FAUXDEX,
        NODE_THREAD_COWRITER,
        NODE_THREAD_ADMIN,
        NODE_THREAD_ROOT,
        NODE_THREAD_WEB,
        NODE_THREAD_TERMINAL,
    };
    const char *thread_ids[THREAD_CARD_COUNT] = {
        "thread:fennix",
        "thread:fauxnix",
        "thread:fauxdex",
        "thread:cowriter",
        "thread:admin",
        "thread:root",
        "thread:web",
        "thread:terminal",
    };
    const char *thread_titles[THREAD_CARD_COUNT] = {
        "Fennix",
        "Fauxnix",
        "Fauxdex",
        "Cowriter",
        "Admin",
        "Root",
        "Web",
        "Terminal",
    };
    const char *thread_descriptions[THREAD_CARD_COUNT] = {
        "Local assistant",
        "Workspace",
        "Workspace agent loop",
        "Notes and drafts",
        "Git-backed system state",
        "Administrator shell",
        "Firefox workspace",
        "Command line",
    };
    const char *thread_actions[THREAD_CARD_COUNT] = {
        "thread:fennix",
        "thread:fauxnix",
        "thread:fauxdex",
        "thread:cowriter",
        "thread:admin",
        "thread:root",
        "thread:web",
        "thread:terminal",
    };
    const int thread_x[THREAD_CARD_COUNT] = {1900, 2260, 2620, 2980, 1900, 2260, 2620, 2980};
    const int thread_y[THREAD_CARD_COUNT] = {80, 80, 80, 80, 370, 370, 370, 370};
    for (int i = 0; i < THREAD_CARD_COUNT; i++) {
        GtkWidget *thread_card = make_thread_card(app, i, thread_titles[i], thread_descriptions[i], thread_actions[i]);
        gtk_fixed_put(
            GTK_FIXED(app->map_canvas),
            map_wrap_card(app, thread_nodes[i], thread_card, thread_ids[i], thread_titles[i], thread_x[i], thread_y[i], 320, 230),
            thread_x[i],
            thread_y[i]
        );
    }

    app_load_map_positions(app);
    app_layout_map(app);
    gtk_container_add(GTK_CONTAINER(scroll), app->map_canvas);
    gtk_box_pack_start(GTK_BOX(main), scroll, TRUE, TRUE, 0);
    return main;
}

static void launcher_action_clicked(GtkButton *button, gpointer user_data) {
    Launcher *launcher = (Launcher *)user_data;
    const char *action = (const char *)g_object_get_data(G_OBJECT(button), "action");
    const char *label = gtk_button_get_label(button);
    if (action == NULL) {
        return;
    }
    if (g_strcmp0(action, "chat:send") == 0) {
        launcher_send_chat(launcher);
        return;
    }
    run_action(action);
    if (launcher != NULL && label != NULL) {
        char *status = g_strdup_printf("Opened %s", label);
        set_label(launcher->status_line, status);
        g_free(status);
    }
}

static GtkWidget *make_launcher_button(Launcher *launcher, const char *label, const char *action) {
    GtkWidget *button = gtk_button_new_with_label(label);
    gtk_widget_set_hexpand(button, TRUE);
    g_object_set_data_full(G_OBJECT(button), "action", g_strdup(action), g_free);
    g_signal_connect(button, "clicked", G_CALLBACK(launcher_action_clicked), launcher);
    return button;
}

static gboolean text_has_content(const char *text) {
    char *copy = g_strdup(text != NULL ? text : "");
    g_strstrip(copy);
    gboolean has_content = copy[0] != '\0';
    g_free(copy);
    return has_content;
}

typedef struct {
    Launcher *launcher;
    char *message;
} ChatRequest;

typedef struct {
    Launcher *launcher;
    char *response;
    gboolean ok;
} ChatResult;

static char *chat_payload_json(const char *message) {
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "message");
    json_builder_add_string_value(builder, message != NULL ? message : "");
    json_builder_set_member_name(builder, "route");
    json_builder_add_string_value(builder, "local");
    json_builder_end_object(builder);

    JsonNode *root = json_builder_get_root(builder);
    JsonGenerator *generator = json_generator_new();
    json_generator_set_root(generator, root);
    char *payload = json_generator_to_data(generator, NULL);
    json_node_free(root);
    g_object_unref(generator);
    g_object_unref(builder);
    return payload;
}

static gboolean launcher_finish_chat(gpointer user_data) {
    ChatResult *result = (ChatResult *)user_data;
    Launcher *launcher = result->launcher;
    if (launcher != NULL) {
        set_label(launcher->chat_output, result->response);
        set_label(launcher->status_line, result->ok ? "Fennix replied" : "Fennix chat failed");
        if (launcher->chat_entry != NULL) {
            gtk_widget_set_sensitive(launcher->chat_entry, TRUE);
            gtk_widget_grab_focus(launcher->chat_entry);
        }
        launcher->chat_busy = FALSE;
    }
    g_free(result->response);
    g_free(result);
    return G_SOURCE_REMOVE;
}

static gpointer launcher_chat_worker(gpointer user_data) {
    ChatRequest *request = (ChatRequest *)user_data;
    JsonParser *parser = NULL;
    char *payload = chat_payload_json(request->message);
    gboolean ok = post_json_timeout(API_BASE "/chat", payload, 180000L, &parser);
    g_free(payload);

    char *response = NULL;
    if (parser != NULL) {
        JsonNode *root = json_parser_get_root(parser);
        if (root != NULL && JSON_NODE_HOLDS_OBJECT(root)) {
            JsonObject *object = json_node_get_object(root);
            response = g_strdup(string_member(object, ok ? "response" : "error", ok ? "Fennix replied with no text." : "Fennix chat failed."));
            if (!ok && !text_has_content(response)) {
                response = g_strdup(string_member(object, "response", "Fennix chat failed."));
            }
        }
        g_object_unref(parser);
    }
    if (!text_has_content(response)) {
        g_free(response);
        response = g_strdup(ok ? "Fennix replied with no text." : "Fennix chat failed.");
    }

    ChatResult *result = g_new0(ChatResult, 1);
    result->launcher = request->launcher;
    result->response = response;
    result->ok = ok;
    g_idle_add(launcher_finish_chat, result);

    g_free(request->message);
    g_free(request);
    return NULL;
}

static void launcher_send_chat(Launcher *launcher) {
    if (launcher == NULL || launcher->chat_entry == NULL) {
        return;
    }
    if (launcher->chat_busy) {
        set_label(launcher->status_line, "Fennix is still thinking");
        return;
    }
    const char *entry_text = gtk_entry_get_text(GTK_ENTRY(launcher->chat_entry));
    if (!text_has_content(entry_text)) {
        set_label(launcher->status_line, "Ask Fennix something first");
        return;
    }

    char *message = g_strdup(entry_text);
    gtk_entry_set_text(GTK_ENTRY(launcher->chat_entry), "");
    gtk_widget_set_sensitive(launcher->chat_entry, FALSE);
    set_label(launcher->chat_output, "Thinking...");
    set_label(launcher->status_line, "Fennix is thinking");
    launcher->chat_busy = TRUE;

    ChatRequest *request = g_new0(ChatRequest, 1);
    request->launcher = launcher;
    request->message = message;
    g_thread_unref(g_thread_new("fennix-chat", launcher_chat_worker, request));
}

static void launcher_chat_activate(GtkEntry *entry, gpointer user_data) {
    (void)entry;
    launcher_send_chat((Launcher *)user_data);
}

static char *compact_clipboard_text(const char *text, glong limit) {
    char *copy = g_strdup(text != NULL ? text : "");
    g_strstrip(copy);
    for (char *cursor = copy; *cursor != '\0'; cursor++) {
        if (*cursor == '\n' || *cursor == '\r' || *cursor == '\t') {
            *cursor = ' ';
        }
    }
    if (copy[0] == '\0') {
        g_free(copy);
        return g_strdup("Clipboard empty. Copy text, press Paste, then Save.");
    }
    if (g_utf8_strlen(copy, -1) <= limit) {
        return copy;
    }
    char *head = g_utf8_substring(copy, 0, limit);
    char *result = g_strdup_printf("%s...", head);
    g_free(head);
    g_free(copy);
    return result;
}

static char *read_system_clipboard_text(void) {
    GtkClipboard *clipboard = gtk_clipboard_get(GDK_SELECTION_CLIPBOARD);
    if (clipboard != NULL) {
        char *text = gtk_clipboard_wait_for_text(clipboard);
        if (text_has_content(text)) {
            return text;
        }
        g_free(text);
    }

    char *stdout_data = NULL;
    char *stderr_data = NULL;
    int status = 0;
    GError *error = NULL;
    char *argv[] = {"wl-paste", "--no-newline", NULL};
    gboolean ok = g_spawn_sync(
        NULL,
        argv,
        NULL,
        G_SPAWN_SEARCH_PATH,
        NULL,
        NULL,
        &stdout_data,
        &stderr_data,
        &status,
        &error
    );
    if (!ok && error != NULL) {
        g_warning("clipboard read failed: %s", error->message);
        g_error_free(error);
    }
    g_free(stderr_data);
    if (ok && status == 0 && text_has_content(stdout_data)) {
        return stdout_data;
    }
    g_free(stdout_data);
    return g_strdup("");
}

static char *clipboard_payload_json(const char *text) {
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "content");
    json_builder_add_string_value(builder, text != NULL ? text : "");
    json_builder_set_member_name(builder, "source");
    json_builder_add_string_value(builder, "native_desktop");
    json_builder_end_object(builder);

    JsonNode *root = json_builder_get_root(builder);
    JsonGenerator *generator = json_generator_new();
    json_generator_set_root(generator, root);
    char *payload = json_generator_to_data(generator, NULL);
    json_node_free(root);
    g_object_unref(generator);
    g_object_unref(builder);
    return payload;
}

static void app_set_clipboard_text(App *app, const char *text) {
    if (app == NULL) {
        return;
    }
    g_free(app->clipboard_text);
    app->clipboard_text = g_strdup(text != NULL ? text : "");
    char *preview = compact_clipboard_text(app->clipboard_text, 260);
    set_label(app->clipboard_preview, preview);
    g_free(preview);
}

static void app_refresh_clipboard(App *app) {
    char *text = read_system_clipboard_text();
    app_set_clipboard_text(app, text);
    set_status(app, text_has_content(text) ? "Clipboard staged" : "Clipboard empty");
    g_free(text);
}

static void app_save_clipboard(App *app) {
    if (app == NULL) {
        return;
    }
    if (!text_has_content(app->clipboard_text)) {
        app_refresh_clipboard(app);
    }
    if (!text_has_content(app->clipboard_text)) {
        set_status(app, "Clipboard empty");
        return;
    }

    char *payload = clipboard_payload_json(app->clipboard_text);
    JsonParser *parser = NULL;
    gboolean ok = post_json(API_BASE "/clipboard/text", payload, &parser);
    g_free(payload);
    if (parser != NULL) {
        g_object_unref(parser);
    }
    if (!ok) {
        set_status(app, "Clipboard save failed");
        return;
    }
    set_status(app, "Saved clipboard note");
    update_summary(app);
}

static void app_clear_clipboard(App *app) {
    JsonParser *parser = NULL;
    gboolean ok = post_json(API_BASE "/clipboard/clear", "{}", &parser);
    if (parser != NULL) {
        g_object_unref(parser);
    }
    if (!ok) {
        set_status(app, "Clipboard clear failed");
        return;
    }
    app_set_clipboard_text(app, "");
    set_status(app, "Clipboard list cleared");
    update_summary(app);
}

static void app_handle_clipboard_action(App *app, const char *action) {
    if (g_strcmp0(action, "clipboard:paste") == 0) {
        app_refresh_clipboard(app);
    } else if (g_strcmp0(action, "clipboard:save") == 0) {
        app_save_clipboard(app);
    } else if (g_strcmp0(action, "clipboard:clear") == 0) {
        app_clear_clipboard(app);
    }
}

static void launcher_show(Launcher *launcher) {
    if (launcher == NULL || launcher->window == NULL) {
        return;
    }
    launcher->visible = TRUE;
    gtk_widget_show_all(launcher->window);
    gtk_window_present(GTK_WINDOW(launcher->window));
}

static void launcher_hide(Launcher *launcher) {
    if (launcher == NULL || launcher->window == NULL) {
        return;
    }
    launcher->visible = FALSE;
    gtk_widget_hide(launcher->window);
}

static gboolean launcher_update_summary(gpointer user_data) {
    Launcher *launcher = (Launcher *)user_data;
    JsonParser *parser = NULL;
    if (!fetch_json(API_BASE "/summary", &parser)) {
        set_label(launcher->status_line, "Fauxd offline");
        set_label(launcher->telemetry_line, "Waiting for local services");
        return G_SOURCE_CONTINUE;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root == NULL || !JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return G_SOURCE_CONTINUE;
    }
    JsonObject *summary = json_node_get_object(root);
    JsonObject *telemetry = object_member(summary, "telemetry");
    const char *memory_text = string_member(telemetry, "memory_text", "RAM n/a");
    const char *battery_text = string_member(telemetry, "battery_text", "BAT n/a");
    const char *network_text = string_member(telemetry, "network_text", "Network n/a");
    double cpu = double_member(telemetry, "cpu_percent", 0.0);
    double load = double_member(telemetry, "load_percent", 0.0);
    char *line = g_strdup_printf("CPU %.0f%%   Load %.0f%%   %s   %s   %s", cpu, load, memory_text, battery_text, network_text);
    set_label(launcher->telemetry_line, line);
    g_free(line);

    set_label(launcher->status_line, "Native launcher ready");
    g_object_unref(parser);
    return G_SOURCE_CONTINUE;
}

static gboolean launcher_poll_command(gpointer user_data) {
    Launcher *launcher = (Launcher *)user_data;
    char *path = runtime_path("native-launcher-command");
    char *contents = NULL;
    if (g_file_get_contents(path, &contents, NULL, NULL)) {
        remove(path);
        if (g_str_has_prefix(contents, "show")) {
            launcher_show(launcher);
        } else if (g_str_has_prefix(contents, "hide")) {
            launcher_hide(launcher);
        } else if (launcher->visible) {
            launcher_hide(launcher);
        } else {
            launcher_show(launcher);
        }
    }
    g_free(contents);
    g_free(path);
    return G_SOURCE_CONTINUE;
}

static GtkWidget *make_launcher_panel(Launcher *launcher) {
    GtkWidget *main = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
    add_class(main, "launcher-main");
    gtk_widget_set_hexpand(main, TRUE);
    gtk_widget_set_vexpand(main, TRUE);
    gtk_widget_set_size_request(main, -1, LAUNCHER_HEIGHT);

    GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    add_class(header, "launcher-header");
    GtkWidget *mark = make_label("Fennix", "launcher-title", 0.0f);
    gtk_widget_set_hexpand(mark, TRUE);
    gtk_box_pack_start(GTK_BOX(header), mark, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(header), make_launcher_button(launcher, "Hide", "launcher"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(main), header, FALSE, FALSE, 0);

    launcher->telemetry_line = make_label("Starting telemetry", "muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(main), launcher->telemetry_line, FALSE, FALSE, 0);

    GtkWidget *chat = make_card("Chat");
    gtk_widget_set_vexpand(chat, TRUE);

    GtkWidget *chat_scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(chat_scroll), GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
    gtk_widget_set_size_request(chat_scroll, -1, 210);
    add_class(chat_scroll, "chat-output-shell");
    launcher->chat_output = make_label("Ask Fennix from here. Local actions still go through Fennix.", "chat-output", 0.0f);
    gtk_label_set_ellipsize(GTK_LABEL(launcher->chat_output), PANGO_ELLIPSIZE_NONE);
    gtk_label_set_selectable(GTK_LABEL(launcher->chat_output), TRUE);
    gtk_container_add(GTK_CONTAINER(chat_scroll), launcher->chat_output);
    gtk_box_pack_start(GTK_BOX(chat), chat_scroll, TRUE, TRUE, 0);

    GtkWidget *chat_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    launcher->chat_entry = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(launcher->chat_entry), "Ask Fennix");
    g_signal_connect(launcher->chat_entry, "activate", G_CALLBACK(launcher_chat_activate), launcher);
    gtk_box_pack_start(GTK_BOX(chat_row), launcher->chat_entry, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(chat_row), make_launcher_button(launcher, "Send", "chat:send"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(chat), chat_row, FALSE, FALSE, 0);

    gtk_box_pack_start(GTK_BOX(main), chat, TRUE, TRUE, 0);

    GtkWidget *footer = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    launcher->status_line = make_label("Native launcher starting", "route-pill", 0.0f);
    gtk_widget_set_hexpand(launcher->status_line, TRUE);
    gtk_box_pack_start(GTK_BOX(footer), launcher->status_line, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(main), footer, FALSE, FALSE, 0);

    return main;
}

static void text_view_set_text(GtkWidget *text_view, const char *text) {
    GtkTextBuffer *buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(text_view));
    gtk_text_buffer_set_text(buffer, text != NULL ? text : "", -1);
}

static char *url_escape_value(const char *value) {
    CURL *curl = curl_easy_init();
    if (curl == NULL) {
        return g_strdup("");
    }
    char *escaped = curl_easy_escape(curl, value != NULL ? value : "", 0);
    char *copy = g_strdup(escaped != NULL ? escaped : "");
    if (escaped != NULL) {
        curl_free(escaped);
    }
    curl_easy_cleanup(curl);
    return copy;
}

static void files_view_clear_paths(FilesView *view) {
    for (int i = 0; i < FILE_VIEW_ROWS; i++) {
        g_free(view->paths[i]);
        view->paths[i] = NULL;
    }
}

static char *files_view_current_thread(FilesView *view) {
    if (view == NULL || view->thread_combo == NULL) {
        return g_strdup("fauxnix");
    }
    char *active = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(view->thread_combo));
    if (!text_has_content(active)) {
        g_free(active);
        return g_strdup("fauxnix");
    }
    return active;
}

static char *files_view_search_query(FilesView *view) {
    if (view == NULL || view->search_entry == NULL) {
        return g_strdup("");
    }
    const char *text = gtk_entry_get_text(GTK_ENTRY(view->search_entry));
    return g_strdup(text != NULL ? text : "");
}

static char *file_action_payload_json(const char *path, const char *thread_id) {
    JsonBuilder *builder = json_builder_new();
    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "path");
    json_builder_add_string_value(builder, path != NULL ? path : "");
    json_builder_set_member_name(builder, "thread");
    json_builder_add_string_value(builder, thread_id != NULL ? thread_id : "fauxnix");
    json_builder_end_object(builder);

    JsonNode *root = json_builder_get_root(builder);
    JsonGenerator *generator = json_generator_new();
    json_generator_set_root(generator, root);
    char *payload = json_generator_to_data(generator, NULL);
    json_node_free(root);
    g_object_unref(generator);
    g_object_unref(builder);
    return payload;
}

static gboolean files_view_post_file_action(FilesView *view, const char *endpoint, const char *verb, gboolean thread_status) {
    if (view == NULL || !text_has_content(view->selected_path)) {
        set_label(view->action_status, "Select a file first.");
        return FALSE;
    }
    char *thread = files_view_current_thread(view);
    char *payload = file_action_payload_json(view->selected_path, thread);
    char *url = g_strdup_printf(API_BASE "%s", endpoint);
    JsonParser *parser = NULL;
    gboolean ok = post_json(url, payload, &parser);
    g_free(url);
    g_free(payload);

    const char *message = NULL;
    if (parser != NULL) {
        JsonNode *root = json_parser_get_root(parser);
        if (root != NULL && JSON_NODE_HOLDS_OBJECT(root)) {
            JsonObject *object = json_node_get_object(root);
            message = string_member(object, ok ? "status" : "error", NULL);
        }
    }
    if (ok) {
        char *status = thread_status
            ? g_strdup_printf("%s %s.", verb, thread)
            : g_strdup_printf("%s.", verb);
        set_label(view->action_status, status);
        g_free(status);
    } else {
        set_label(view->action_status, message != NULL ? message : "File action failed.");
    }
    if (parser != NULL) {
        g_object_unref(parser);
    }
    g_free(thread);
    return ok;
}

static char *files_view_row_text(JsonObject *row) {
    const char *title = string_member(row, "title", "File");
    const char *root = string_member(row, "root", "Files");
    const char *kind = string_member(row, "kind", "file");
    const char *evidence = string_member(row, "evidence_label", "");
    const char *confidence = string_member(row, "source_confidence", "");
    const char *relative = string_member(row, "relative_path", "");
    const char *match = string_member(row, "match", "");
    const char *snippet = string_member(row, "snippet", "");
    int size = int_member(row, "size", 0);
    int updated_at = int_member(row, "updated_at", 0);
    char when[32] = "";
    if (updated_at > 0) {
        time_t stamp = (time_t)updated_at;
        struct tm local = *localtime(&stamp);
        strftime(when, sizeof(when), "%a %H:%M", &local);
    }
    char *size_text = format_file_size(size);
    char *label = NULL;
    if (evidence[0] != '\0' && confidence[0] != '\0') {
        label = g_strdup_printf("%s / %s", evidence, confidence);
    } else if (evidence[0] != '\0') {
        label = g_strdup(evidence);
    } else {
        label = g_strdup(kind);
    }
    char *meta = when[0] != '\0'
        ? g_strdup_printf("%s / %s  -  %s  -  %s", root, label, when, size_text)
        : g_strdup_printf("%s / %s  -  %s", root, label, size_text);
    char *match_line = NULL;
    if (snippet[0] != '\0') {
        match_line = g_strdup_printf("%s match: %s", match[0] != '\0' ? match : "content", snippet);
    } else if (match[0] != '\0') {
        match_line = g_strdup_printf("%s match", match);
    }
    char *result = NULL;
    if (relative[0] != '\0' && match_line != NULL) {
        result = g_strdup_printf("%s\n%s\n%s\n%s", title, meta, relative, match_line);
    } else if (relative[0] != '\0') {
        result = g_strdup_printf("%s\n%s\n%s", title, meta, relative);
    } else if (match_line != NULL) {
        result = g_strdup_printf("%s\n%s\n%s", title, meta, match_line);
    } else {
        result = g_strdup_printf("%s\n%s", title, meta);
    }
    g_free(match_line);
    g_free(label);
    g_free(meta);
    g_free(size_text);
    return result;
}

static void files_view_show_preview(FilesView *view, const char *path) {
    if (view == NULL || !text_has_content(path)) {
        return;
    }
    if (view->preview_image != NULL) {
        gtk_widget_hide(view->preview_image);
    }
    g_free(view->selected_path);
    view->selected_path = g_strdup(path);
    char *escaped = url_escape_value(path);
    char *url = g_strdup_printf(API_BASE "/files/preview?path=%s", escaped);
    g_free(escaped);

    JsonParser *parser = NULL;
    gboolean ok = fetch_json(url, &parser);
    g_free(url);
    if (!ok || parser == NULL) {
        set_label(view->detail_title, "Preview unavailable");
        set_label(view->detail_meta, "Fauxd did not return file details.");
        text_view_set_text(view->preview_text, "");
        if (parser != NULL) {
            g_object_unref(parser);
        }
        return;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root == NULL || !JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return;
    }
    JsonObject *object = json_node_get_object(root);
    if (!json_object_has_member(object, "ok") || !json_object_get_boolean_member(object, "ok")) {
        set_label(view->detail_title, "Preview blocked");
        set_label(view->detail_meta, string_member(object, "error", "File is outside the watched roots."));
        text_view_set_text(view->preview_text, "");
        g_object_unref(parser);
        return;
    }

    JsonObject *file = object_member(object, "file");
    const char *title = string_member(file, "title", "File");
    const char *file_path = string_member(file, "path", path);
    const char *relative = string_member(file, "relative_path", "");
    const char *root_name = string_member(file, "root", "Files");
    const char *kind = string_member(file, "kind", "file");
    int size = int_member(file, "size", 0);
    int updated_at = int_member(file, "updated_at", 0);
    char when[48] = "";
    if (updated_at > 0) {
        time_t stamp = (time_t)updated_at;
        struct tm local = *localtime(&stamp);
        strftime(when, sizeof(when), "%A %H:%M", &local);
    }
    char *size_text = format_file_size(size);
    char *meta = g_strdup_printf("%s / %s  -  %s  -  %s", root_name, kind, when[0] ? when : "mtime n/a", size_text);
    char *detail = relative[0] != '\0'
        ? g_strdup_printf("%s\n%s", meta, relative)
        : g_strdup(meta);
    set_label(view->detail_title, title);
    set_label(view->detail_meta, detail);

    const char *preview = string_member(object, "preview", "");
    const char *preview_kind = string_member(object, "preview_kind", "metadata");
    gboolean truncated = json_object_has_member(object, "truncated") && json_object_get_boolean_member(object, "truncated");
    if (g_strcmp0(preview_kind, "image") == 0 && view->preview_image != NULL) {
        GError *error = NULL;
        GdkPixbuf *pixbuf = gdk_pixbuf_new_from_file_at_scale(file_path, 520, 320, TRUE, &error);
        if (pixbuf != NULL) {
            gtk_image_set_from_pixbuf(GTK_IMAGE(view->preview_image), pixbuf);
            gtk_widget_show(view->preview_image);
            g_object_unref(pixbuf);
        } else {
            gtk_widget_hide(view->preview_image);
            if (error != NULL) {
                g_warning("image preview failed: %s", error->message);
                g_error_free(error);
            }
        }
    }
    char *body = NULL;
    if (preview[0] != '\0') {
        body = truncated
            ? g_strdup_printf("%s\n\n[preview truncated]\n\n%s", file_path, preview)
            : g_strdup_printf("%s\n\n%s", file_path, preview);
    } else {
        body = g_strdup_printf("%s\n\nPreview type: %s\nText preview is not available for this file yet.", file_path, preview_kind);
    }
    text_view_set_text(view->preview_text, body);

    g_free(body);
    g_free(detail);
    g_free(meta);
    g_free(size_text);
    g_object_unref(parser);
}

static void files_view_load(FilesView *view) {
    if (view == NULL) {
        return;
    }
    char *url = NULL;
    char *search = files_view_search_query(view);
    gboolean pinned_root = g_strcmp0(view->root_filter, "Pinned") == 0;
    gboolean attached_root = g_strcmp0(view->root_filter, "Attached") == 0;
    gboolean has_search = text_has_content(search) && !attached_root && !pinned_root;
    if (attached_root) {
        char *thread = files_view_current_thread(view);
        char *escaped = url_escape_value(thread);
        url = g_strdup_printf(API_BASE "/files/attachments?thread=%s", escaped);
        g_free(escaped);
        g_free(thread);
    } else if (pinned_root) {
        url = g_strdup_printf(API_BASE "/files/pins?limit=%d", FILE_VIEW_ROWS);
    } else if (has_search) {
        char *escaped_search = url_escape_value(search);
        gboolean content = view->content_search != NULL && gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(view->content_search));
        if (text_has_content(view->root_filter)) {
            char *escaped_root = url_escape_value(view->root_filter);
            url = g_strdup_printf(API_BASE "/files/search?limit=%d&q=%s&root=%s&content=%d", FILE_VIEW_ROWS, escaped_search, escaped_root, content ? 1 : 0);
            g_free(escaped_root);
        } else {
            url = g_strdup_printf(API_BASE "/files/search?limit=%d&q=%s&content=%d", FILE_VIEW_ROWS, escaped_search, content ? 1 : 0);
        }
        g_free(escaped_search);
    } else if (text_has_content(view->root_filter)) {
        char *escaped = url_escape_value(view->root_filter);
        url = g_strdup_printf(API_BASE "/files/recent?limit=%d&root=%s", FILE_VIEW_ROWS, escaped);
        g_free(escaped);
    } else {
        url = g_strdup_printf(API_BASE "/files/recent?limit=%d", FILE_VIEW_ROWS);
    }
    g_free(search);

    JsonParser *parser = NULL;
    gboolean ok = fetch_json(url, &parser);
    g_free(url);
    files_view_clear_paths(view);
    if (!ok || parser == NULL) {
        set_label(view->scope_label, "Fauxd file index unavailable");
        for (int i = 0; i < FILE_VIEW_ROWS; i++) {
            gtk_button_set_label(GTK_BUTTON(view->rows[i]), i == 0 ? "No file data available." : "");
            gtk_widget_set_sensitive(view->rows[i], FALSE);
        }
        if (parser != NULL) {
            g_object_unref(parser);
        }
        return;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root == NULL || !JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return;
    }
    JsonObject *object = json_node_get_object(root);
    JsonObject *files = attached_root
        ? object_member(object, "attachments")
        : pinned_root
            ? object_member(object, "pins")
            : object_member(object, "files");
    int count = int_member(files, "count", 0);
    int scanned = int_member(files, "scanned", 0);
    const char *server_query = string_member(files, "query", "");
    char *scope = NULL;
    if (attached_root) {
        char *thread = files_view_current_thread(view);
        scope = g_strdup_printf("Attached to %s - %d file%s", thread, count, count == 1 ? "" : "s");
        g_free(thread);
    } else if (pinned_root) {
        scope = g_strdup_printf("Pinned evidence - %d file%s", count, count == 1 ? "" : "s");
    } else if (text_has_content(server_query) && text_has_content(view->root_filter)) {
        scope = g_strdup_printf("Search \"%s\" in %s - %d matches / %d scanned", server_query, view->root_filter, count, scanned);
    } else if (text_has_content(server_query)) {
        scope = g_strdup_printf("Search \"%s\" - %d matches / %d scanned", server_query, count, scanned);
    } else if (text_has_content(view->root_filter)) {
        scope = g_strdup_printf("%s - %d candidates / %d scanned", view->root_filter, count, scanned);
    } else {
        scope = g_strdup_printf("Recent - %d candidates / %d scanned", count, scanned);
    }
    set_label(view->scope_label, scope);
    g_free(scope);

    JsonArray *array = array_member(files, "recent");
    guint row_count = array != NULL ? json_array_get_length(array) : 0;
    for (int i = 0; i < FILE_VIEW_ROWS; i++) {
        if ((guint)i < row_count) {
            JsonObject *row = json_array_get_object_element(array, (guint)i);
            char *text = files_view_row_text(row);
            gtk_button_set_label(GTK_BUTTON(view->rows[i]), text);
            set_button_label_align(view->rows[i], 0.0f);
            view->paths[i] = g_strdup(string_member(row, "path", ""));
            gtk_widget_set_sensitive(view->rows[i], text_has_content(view->paths[i]));
            gtk_widget_show(view->rows[i]);
            g_free(text);
        } else {
            gtk_button_set_label(GTK_BUTTON(view->rows[i]), i == 0
                ? (text_has_content(server_query) ? "No matching files in this scope." : "No recent files in this scope.")
                : "");
            gtk_widget_set_sensitive(view->rows[i], FALSE);
            if (i == 0) {
                gtk_widget_show(view->rows[i]);
            } else {
                gtk_widget_hide(view->rows[i]);
            }
        }
    }

    if (row_count > 0 && view->paths[0] != NULL) {
        files_view_show_preview(view, view->paths[0]);
    } else {
        set_label(view->detail_title, "Select a file");
        set_label(view->detail_meta, "Recent file details will appear here.");
        text_view_set_text(view->preview_text, "");
    }
    g_object_unref(parser);
}

static void files_root_clicked(GtkButton *button, gpointer user_data) {
    FilesView *view = (FilesView *)user_data;
    const char *root = (const char *)g_object_get_data(G_OBJECT(button), "root-filter");
    g_free(view->root_filter);
    view->root_filter = g_strdup(root != NULL ? root : "");
    files_view_load(view);
}

static void files_row_clicked(GtkButton *button, gpointer user_data) {
    FilesView *view = (FilesView *)user_data;
    int index = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(button), "row-index"));
    if (index < 0 || index >= FILE_VIEW_ROWS || view->paths[index] == NULL) {
        return;
    }
    files_view_show_preview(view, view->paths[index]);
}

static void files_thread_changed(GtkComboBoxText *combo, gpointer user_data) {
    (void)combo;
    FilesView *view = (FilesView *)user_data;
    if (g_strcmp0(view->root_filter, "Attached") == 0) {
        files_view_load(view);
    }
}

static void files_search_submitted(GtkWidget *widget, gpointer user_data) {
    (void)widget;
    files_view_load((FilesView *)user_data);
}

static void files_clear_search_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (view != NULL && view->search_entry != NULL) {
        gtk_entry_set_text(GTK_ENTRY(view->search_entry), "");
    }
    files_view_load(view);
}

static void files_content_search_toggled(GtkToggleButton *button, gpointer user_data) {
    (void)button;
    files_view_load((FilesView *)user_data);
}

static void files_index_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (view == NULL) {
        return;
    }

    char *url = NULL;
    if (text_has_content(view->root_filter) && g_strcmp0(view->root_filter, "Attached") != 0) {
        char *escaped = url_escape_value(view->root_filter);
        url = g_strdup_printf(API_BASE "/files/index?limit=24&rebuild=1&root=%s", escaped);
        g_free(escaped);
    } else {
        url = g_strdup(API_BASE "/files/index?limit=24&rebuild=1");
    }

    JsonParser *parser = NULL;
    gboolean ok = fetch_json(url, &parser);
    g_free(url);
    if (!ok || parser == NULL) {
        set_label(view->action_status, "File index failed.");
        if (parser != NULL) {
            g_object_unref(parser);
        }
        return;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root != NULL && JSON_NODE_HOLDS_OBJECT(root)) {
        JsonObject *object = json_node_get_object(root);
        JsonObject *index = object_member(object, "index");
        int count = int_member(index, "count", 0);
        int scanned = int_member(index, "scanned", 0);
        const char *path = string_member(index, "path", "");
        char *status = path[0] != '\0'
            ? g_strdup_printf("Indexed %d files / %d scanned. Snapshot: %s", count, scanned, path)
            : g_strdup_printf("Indexed %d files / %d scanned.", count, scanned);
        set_label(view->action_status, status);
        g_free(status);
    } else {
        set_label(view->action_status, "File index completed.");
    }
    g_object_unref(parser);
    if (g_strcmp0(view->root_filter, "Attached") != 0) {
        files_view_load(view);
    }
}

static void files_attach_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (files_view_post_file_action(view, "/files/attach", "Attached to", TRUE)) {
        if (g_strcmp0(view->root_filter, "Attached") == 0) {
            files_view_load(view);
        }
    }
}

static void files_promote_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    files_view_post_file_action(view, "/files/promote", "Promoted from", TRUE);
}

static void files_pin_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (files_view_post_file_action(view, "/files/pin", "Pinned", FALSE)) {
        if (g_strcmp0(view->root_filter, "Pinned") == 0) {
            files_view_load(view);
        }
    }
}

static void files_unpin_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (files_view_post_file_action(view, "/files/unpin", "Unpinned", FALSE)) {
        if (g_strcmp0(view->root_filter, "Pinned") == 0) {
            files_view_load(view);
        }
    }
}

static void files_show_uri(FilesView *view, const char *path, const char *success_status) {
    if (view == NULL || !text_has_content(path)) {
        set_label(view->action_status, "Select a file first.");
        return;
    }
    GFile *file = g_file_new_for_path(path);
    char *uri = g_file_get_uri(file);
    GError *error = NULL;
    gboolean ok = gtk_show_uri_on_window(GTK_WINDOW(view->window), uri, GDK_CURRENT_TIME, &error);
    if (ok) {
        set_label(view->action_status, success_status);
    } else {
        set_label(view->action_status, error != NULL ? error->message : "Open action failed.");
    }
    if (error != NULL) {
        g_error_free(error);
    }
    g_free(uri);
    g_object_unref(file);
}

static void files_open_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    files_show_uri(view, view != NULL ? view->selected_path : NULL, "Opened selected file.");
}

static void files_reveal_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (view == NULL || !text_has_content(view->selected_path)) {
        set_label(view->action_status, "Select a file first.");
        return;
    }
    char *parent = g_path_get_dirname(view->selected_path);
    files_show_uri(view, parent, "Opened containing folder.");
    g_free(parent);
}

static void files_copy_path_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    FilesView *view = (FilesView *)user_data;
    if (view == NULL || !text_has_content(view->selected_path)) {
        set_label(view->action_status, "Select a file first.");
        return;
    }
    GtkClipboard *clipboard = gtk_clipboard_get(GDK_SELECTION_CLIPBOARD);
    if (clipboard == NULL) {
        set_label(view->action_status, "Clipboard unavailable.");
        return;
    }
    gtk_clipboard_set_text(clipboard, view->selected_path, -1);
    gtk_clipboard_store(clipboard);
    set_label(view->action_status, "Copied path to clipboard.");
}

static GtkWidget *make_files_root_button(FilesView *view, const char *label, const char *root_filter) {
    GtkWidget *button = gtk_button_new_with_label(label);
    gtk_widget_set_hexpand(button, TRUE);
    g_object_set_data_full(G_OBJECT(button), "root-filter", g_strdup(root_filter != NULL ? root_filter : ""), g_free);
    g_signal_connect(button, "clicked", G_CALLBACK(files_root_clicked), view);
    return button;
}

static int run_files_view(void) {
    FilesView *view = g_new0(FilesView, 1);
    view->root_filter = g_strdup("");

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    view->window = window;
    gtk_window_set_title(GTK_WINDOW(window), "Archivist Files");
    gtk_window_set_default_size(GTK_WINDOW(window), 1120, 720);
    gtk_window_set_resizable(GTK_WINDOW(window), TRUE);
    enable_glass_window(window, "files-window", 0.98);

    GtkWidget *main = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
    add_class(main, "main");
    add_class(main, "files-main");

    GtkWidget *header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 10);
    GtkWidget *title = make_label("Archivist Files", "hero-title-small", 0.0f);
    view->scope_label = make_label("Loading files", "route-pill", 0.0f);
    gtk_widget_set_hexpand(view->scope_label, TRUE);
    gtk_box_pack_start(GTK_BOX(header), title, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(header), view->scope_label, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(main), header, FALSE, FALSE, 0);

    GtkWidget *search_row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    view->search_entry = gtk_search_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(view->search_entry), "Search filenames, paths, or text");
    gtk_widget_set_hexpand(view->search_entry, TRUE);
    add_class(view->search_entry, "file-search-entry");
    g_signal_connect(view->search_entry, "activate", G_CALLBACK(files_search_submitted), view);
    gtk_box_pack_start(GTK_BOX(search_row), view->search_entry, TRUE, TRUE, 0);
    view->content_search = gtk_check_button_new_with_label("Text");
    g_signal_connect(view->content_search, "toggled", G_CALLBACK(files_content_search_toggled), view);
    gtk_box_pack_start(GTK_BOX(search_row), view->content_search, FALSE, FALSE, 0);
    GtkWidget *search_button = gtk_button_new_with_label("Search");
    g_signal_connect(search_button, "clicked", G_CALLBACK(files_search_submitted), view);
    gtk_box_pack_start(GTK_BOX(search_row), search_button, FALSE, FALSE, 0);
    GtkWidget *clear_button = gtk_button_new_with_label("Clear");
    g_signal_connect(clear_button, "clicked", G_CALLBACK(files_clear_search_clicked), view);
    gtk_box_pack_start(GTK_BOX(search_row), clear_button, FALSE, FALSE, 0);
    GtkWidget *index_button = gtk_button_new_with_label("Index");
    g_signal_connect(index_button, "clicked", G_CALLBACK(files_index_clicked), view);
    gtk_box_pack_start(GTK_BOX(search_row), index_button, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(main), search_row, FALSE, FALSE, 0);

    GtkWidget *body = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_vexpand(body, TRUE);
    gtk_box_pack_start(GTK_BOX(main), body, TRUE, TRUE, 0);

    GtkWidget *rail = make_card("Roots");
    gtk_widget_set_size_request(rail, 190, -1);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Recent", ""), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Downloads", "Downloads"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Pictures", "Pictures"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Threads", "Threads"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Cowriter", "Cowriter"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Repos", "Repos"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Pinned", "Pinned"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(rail), make_files_root_button(view, "Attached", "Attached"), FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(body), rail, FALSE, FALSE, 0);

    GtkWidget *list_card = make_card("Recent Evidence");
    gtk_widget_set_size_request(list_card, 390, -1);
    for (int i = 0; i < FILE_VIEW_ROWS; i++) {
        view->rows[i] = gtk_button_new_with_label(i == 0 ? "Loading files..." : "");
        add_class(view->rows[i], "file-list-button");
        g_object_set_data(G_OBJECT(view->rows[i]), "row-index", GINT_TO_POINTER(i));
        g_signal_connect(view->rows[i], "clicked", G_CALLBACK(files_row_clicked), view);
        set_button_label_align(view->rows[i], 0.0f);
        gtk_box_pack_start(GTK_BOX(list_card), view->rows[i], FALSE, FALSE, 0);
    }
    gtk_box_pack_start(GTK_BOX(body), list_card, FALSE, FALSE, 0);

    GtkWidget *details = make_card("Preview");
    gtk_widget_set_hexpand(details, TRUE);
    gtk_widget_set_vexpand(details, TRUE);
    view->detail_title = make_label("Select a file", "card-title", 0.0f);
    view->detail_meta = make_label("Preview and metadata will appear here.", "small-muted", 0.0f);
    gtk_box_pack_start(GTK_BOX(details), view->detail_title, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(details), view->detail_meta, FALSE, FALSE, 0);

    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    view->thread_combo = gtk_combo_box_text_new();
    const char *thread_ids[] = {"fennix", "fauxnix", "fauxdex", "cowriter", "admin", "root", "web", "terminal"};
    for (guint i = 0; i < G_N_ELEMENTS(thread_ids); i++) {
        gtk_combo_box_text_append_text(GTK_COMBO_BOX_TEXT(view->thread_combo), thread_ids[i]);
    }
    gtk_combo_box_set_active(GTK_COMBO_BOX(view->thread_combo), 1);
    g_signal_connect(view->thread_combo, "changed", G_CALLBACK(files_thread_changed), view);
    gtk_box_pack_start(GTK_BOX(actions), view->thread_combo, FALSE, FALSE, 0);
    GtkWidget *open = gtk_button_new_with_label("Open");
    g_signal_connect(open, "clicked", G_CALLBACK(files_open_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), open, FALSE, FALSE, 0);
    GtkWidget *reveal = gtk_button_new_with_label("Reveal");
    g_signal_connect(reveal, "clicked", G_CALLBACK(files_reveal_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), reveal, FALSE, FALSE, 0);
    GtkWidget *attach = gtk_button_new_with_label("Attach");
    g_signal_connect(attach, "clicked", G_CALLBACK(files_attach_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), attach, FALSE, FALSE, 0);
    GtkWidget *promote = gtk_button_new_with_label("Promote");
    g_signal_connect(promote, "clicked", G_CALLBACK(files_promote_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), promote, FALSE, FALSE, 0);
    GtkWidget *pin = gtk_button_new_with_label("Pin");
    g_signal_connect(pin, "clicked", G_CALLBACK(files_pin_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), pin, FALSE, FALSE, 0);
    GtkWidget *unpin = gtk_button_new_with_label("Unpin");
    g_signal_connect(unpin, "clicked", G_CALLBACK(files_unpin_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), unpin, FALSE, FALSE, 0);
    GtkWidget *copy_path = gtk_button_new_with_label("Copy Path");
    g_signal_connect(copy_path, "clicked", G_CALLBACK(files_copy_path_clicked), view);
    gtk_box_pack_start(GTK_BOX(actions), copy_path, FALSE, FALSE, 0);
    view->action_status = make_label("Select evidence, then attach it to a thread or promote it to memory.", "small-muted", 0.0f);
    gtk_widget_set_hexpand(view->action_status, TRUE);
    gtk_box_pack_start(GTK_BOX(actions), view->action_status, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(details), actions, FALSE, FALSE, 0);

    view->preview_image = gtk_image_new();
    gtk_widget_set_size_request(view->preview_image, -1, 320);
    add_class(view->preview_image, "preview-image");
    gtk_box_pack_start(GTK_BOX(details), view->preview_image, FALSE, FALSE, 0);
    gtk_widget_hide(view->preview_image);

    GtkWidget *preview_scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(preview_scroll), GTK_POLICY_AUTOMATIC, GTK_POLICY_AUTOMATIC);
    gtk_widget_set_vexpand(preview_scroll, TRUE);
    add_class(preview_scroll, "preview-scroll");
    view->preview_text = gtk_text_view_new();
    gtk_text_view_set_editable(GTK_TEXT_VIEW(view->preview_text), FALSE);
    gtk_text_view_set_cursor_visible(GTK_TEXT_VIEW(view->preview_text), FALSE);
    gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(view->preview_text), GTK_WRAP_WORD_CHAR);
    add_class(view->preview_text, "preview-text");
    gtk_container_add(GTK_CONTAINER(preview_scroll), view->preview_text);
    gtk_box_pack_start(GTK_BOX(details), preview_scroll, TRUE, TRUE, 0);
    gtk_box_pack_start(GTK_BOX(body), details, TRUE, TRUE, 0);

    gtk_container_add(GTK_CONTAINER(window), main);
    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    files_view_load(view);
    gtk_widget_show_all(window);
    gtk_main();

    files_view_clear_paths(view);
    g_free(view->selected_path);
    g_free(view->root_filter);
    g_free(view);
    return 0;
}

static int run_launcher(void) {
    Launcher launcher = {0};
    launcher.lock_fd = acquire_named_lock("fauxshell-launcher.lock");
    if (launcher.lock_fd == -2) {
        return 0;
    }

    GdkDisplay *display = gdk_display_get_default();
    GdkMonitor *monitor = NULL;
    GdkRectangle geometry = {0, 0, 1280, 720};
    if (display != NULL) {
        monitor = gdk_display_get_primary_monitor(display);
        if (monitor == NULL && gdk_display_get_n_monitors(display) > 0) {
            monitor = gdk_display_get_monitor(display, 0);
        }
        if (monitor != NULL) {
            gdk_monitor_get_geometry(monitor, &geometry);
        }
    }

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    launcher.window = window;
    gtk_window_set_title(GTK_WINDOW(window), "Fennix Native Launcher");
    gtk_window_set_decorated(GTK_WINDOW(window), FALSE);
    gtk_window_set_resizable(GTK_WINDOW(window), FALSE);
    gtk_window_set_type_hint(GTK_WINDOW(window), GDK_WINDOW_TYPE_HINT_UTILITY);
    gtk_widget_set_size_request(window, geometry.width, LAUNCHER_HEIGHT);
    gtk_window_set_default_size(GTK_WINDOW(window), geometry.width, LAUNCHER_HEIGHT);
    gtk_window_resize(GTK_WINDOW(window), geometry.width, LAUNCHER_HEIGHT);
    enable_glass_window(window, "launcher-window", 0.98);

    gtk_layer_init_for_window(GTK_WINDOW(window));
    gtk_layer_set_namespace(GTK_WINDOW(window), "fennix-launcher");
    gtk_layer_set_layer(GTK_WINDOW(window), GTK_LAYER_SHELL_LAYER_OVERLAY);
    if (monitor != NULL) {
        gtk_layer_set_monitor(GTK_WINDOW(window), monitor);
    }
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_TOP, TRUE);
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_LEFT, TRUE);
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_RIGHT, TRUE);
    gtk_layer_set_exclusive_zone(GTK_WINDOW(window), 0);
    gtk_layer_set_keyboard_mode(GTK_WINDOW(window), GTK_LAYER_SHELL_KEYBOARD_MODE_ON_DEMAND);

    GtkWidget *panel = make_launcher_panel(&launcher);
    gtk_widget_set_size_request(panel, geometry.width, LAUNCHER_HEIGHT);
    gtk_container_add(GTK_CONTAINER(window), panel);
    launcher.visible = TRUE;
    launcher_update_summary(&launcher);
    g_timeout_add_seconds(5, launcher_update_summary, &launcher);
    g_timeout_add(120, launcher_poll_command, &launcher);

    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    gtk_widget_show_all(window);
    gtk_main();

    if (launcher.lock_fd >= 0) {
        close(launcher.lock_fd);
    }
    return 0;
}

static void load_css(void) {
    static const char css[] =
        "window { background: transparent; color: #f1f2ed; font: 11pt Sans; }"
        ".main { padding: 18px; background: transparent; }"
        "window.files-window { background: transparent; }"
        "window.launcher-window { background: transparent; }"
        "window.desktop-window { background: transparent; }"
        ".files-main { padding: 18px; background: rgba(8, 9, 9, 0.68); border: 1px solid rgba(255, 120, 0, 0.22); border-radius: 12px; }"
        ".files-main .card { background: rgba(21, 22, 23, 0.74); border-color: rgba(215, 221, 225, 0.17); }"
        ".files-main .route-pill { background: rgba(18, 20, 22, 0.64); border-color: rgba(215, 221, 225, 0.15); }"
        ".launcher-main { padding: 18px 22px; background: rgba(8, 9, 9, 0.76); border-bottom: 1px solid rgba(255, 120, 0, 0.22); }"
        ".launcher-header { padding-bottom: 4px; }"
        ".launcher-title { color: #ff7800; font-weight: 700; font-size: 18pt; }"
        ".nav { min-height: 48px; }"
        ".desktop-scroll { background: transparent; border: none; }"
        ".desktop-scroll viewport { background: transparent; }"
        ".desktop-scroll scrollbar { background: transparent; border: none; }"
        ".desktop-scroll scrollbar slider { background: rgba(255, 120, 0, 0.55); border-radius: 6px; }"
        ".desktop-scroll scrollbar.vertical slider { min-width: 7px; min-height: 42px; }"
        ".desktop-scroll scrollbar.horizontal slider { min-width: 42px; min-height: 7px; }"
        ".card-map { background: transparent; }"
        ".connection-layer { background: transparent; }"
        ".card { background: rgba(21, 22, 23, 0.78); border: 1px solid rgba(215, 221, 225, 0.16); border-radius: 8px; padding: 16px; box-shadow: 0 18px 42px rgba(0, 0, 0, 0.24); }"
        ".hero-card { padding: 24px; }"
        ".card-title { color: #ff7800; font-weight: 700; font-size: 13pt; }"
        ".hero-title-small { color: #f1f2ed; font-weight: 700; font-size: 24pt; }"
        ".hero-title { color: #f1f2ed; font-weight: 700; font-size: 42pt; }"
        ".eyebrow { color: #ff7800; font-weight: 700; font-size: 10pt; letter-spacing: 0; }"
        ".muted { color: #a2a8ad; }"
        ".small-muted { color: #a2a8ad; font-size: 9pt; }"
        ".strong { color: #f1f2ed; font-weight: 700; }"
        ".weather-symbol { color: #00c8ff; font-size: 36pt; font-weight: 700; }"
        ".route-pill { color: #a2a8ad; background: rgba(18, 20, 22, 0.68); border: 1px solid rgba(215, 221, 225, 0.14); border-radius: 6px; padding: 10px 14px; }"
        ".chat-output-shell { background: rgba(18, 20, 22, 0.70); border: 1px solid rgba(215, 221, 225, 0.14); border-radius: 6px; padding: 10px; }"
        ".chat-output { color: #d7dde1; padding: 8px; }"
        ".clipboard-preview { color: #d7dde1; background: rgba(18, 20, 22, 0.70); border: 1px solid rgba(215, 221, 225, 0.14); border-radius: 6px; padding: 8px 10px; }"
        ".file-row { color: #d7dde1; background: rgba(18, 20, 22, 0.70); border-left: 3px solid #00c8ff; border-radius: 6px; padding: 7px 10px; font-size: 9pt; }"
        ".file-list-button { color: #d7dde1; background: rgba(18, 20, 22, 0.70); border-left: 3px solid #00c8ff; padding: 8px 10px; font-size: 9pt; }"
        ".file-search-entry { color: #f1f2ed; background: rgba(18, 20, 22, 0.68); border: 1px solid rgba(215, 221, 225, 0.18); border-radius: 6px; padding: 8px 10px; }"
        ".preview-image { background: rgba(18, 20, 22, 0.64); border: 1px solid rgba(215, 221, 225, 0.15); border-radius: 6px; padding: 8px; }"
        ".preview-scroll { background: rgba(18, 20, 22, 0.66); border: 1px solid rgba(215, 221, 225, 0.15); border-radius: 6px; }"
        ".preview-text { color: #e4e7ea; background: rgba(18, 20, 22, 0.66); padding: 12px; font-family: monospace; font-size: 10pt; }"
        ".calendar-head { color: #ff7800; font-weight: 700; font-size: 9pt; }"
        ".calendar-day { color: #f1f2ed; background: rgba(31, 35, 40, 0.72); border-radius: 5px; padding: 5px; }"
        ".today { background: #ff7800; color: #080909; font-weight: 700; }"
        "entry { color: #f1f2ed; background: rgba(24, 28, 32, 0.72); border: 1px solid rgba(215, 221, 225, 0.16); border-radius: 6px; padding: 8px 10px; }"
        "button { color: #f1f2ed; background: rgba(36, 40, 45, 0.72); border: 1px solid rgba(215, 221, 225, 0.16); border-radius: 6px; padding: 8px 12px; }"
        "button:hover { border-color: #ff7800; }"
        ".row-button { padding: 8px 10px; }"
        ".bubble-button { color: #d7dde1; background: rgba(18, 20, 22, 0.70); border-color: rgba(215, 221, 225, 0.14); padding: 7px 10px; font-size: 9pt; }"
        ".bubble-button:hover { border-color: #00c8ff; }";

    GtkCssProvider *provider = gtk_css_provider_new();
    gtk_css_provider_load_from_data(provider, css, -1, NULL);
    gtk_style_context_add_provider_for_screen(
        gdk_screen_get_default(),
        GTK_STYLE_PROVIDER(provider),
        GTK_STYLE_PROVIDER_PRIORITY_APPLICATION
    );
    g_object_unref(provider);
}

int main(int argc, char **argv) {
    if (argc > 1 && g_strcmp0(argv[1], "--launcher-toggle") == 0) {
        request_launcher_toggle();
        return 0;
    }

    gtk_init(&argc, &argv);
    curl_global_init(CURL_GLOBAL_DEFAULT);
    load_css();

    if (argc > 1 && g_strcmp0(argv[1], "--launcher") == 0) {
        int result = run_launcher();
        curl_global_cleanup();
        return result;
    }

    if (argc > 1 && g_strcmp0(argv[1], "--files") == 0) {
        int result = run_files_view();
        curl_global_cleanup();
        return result;
    }

    App app = {0};
    app.user = g_strdup(g_get_user_name() != NULL ? g_get_user_name() : "chvk");

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window), "Fauxshell Native Desktop");
    gtk_window_set_decorated(GTK_WINDOW(window), FALSE);
    gtk_window_set_resizable(GTK_WINDOW(window), TRUE);
    gtk_window_set_type_hint(GTK_WINDOW(window), GDK_WINDOW_TYPE_HINT_DESKTOP);
    enable_glass_window(window, "desktop-window", 1.0);

    GdkDisplay *display = gdk_display_get_default();
    GdkMonitor *monitor = NULL;
    GdkRectangle geometry = {0, 0, 1280, 720};
    if (display != NULL) {
        monitor = gdk_display_get_primary_monitor(display);
        if (monitor == NULL && gdk_display_get_n_monitors(display) > 0) {
            monitor = gdk_display_get_monitor(display, 0);
        }
        if (monitor != NULL) {
            gdk_monitor_get_geometry(monitor, &geometry);
        }
    }
    gtk_widget_set_size_request(window, geometry.width, geometry.height);
    gtk_window_resize(GTK_WINDOW(window), geometry.width, geometry.height);

    gtk_layer_init_for_window(GTK_WINDOW(window));
    gtk_layer_set_namespace(GTK_WINDOW(window), "fauxshell");
    gtk_layer_set_layer(GTK_WINDOW(window), GTK_LAYER_SHELL_LAYER_BOTTOM);
    if (monitor != NULL) {
        gtk_layer_set_monitor(GTK_WINDOW(window), monitor);
    }
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_TOP, TRUE);
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_RIGHT, TRUE);
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_BOTTOM, TRUE);
    gtk_layer_set_anchor(GTK_WINDOW(window), GTK_LAYER_SHELL_EDGE_LEFT, TRUE);
    gtk_layer_set_exclusive_zone(GTK_WINDOW(window), 0);
    gtk_layer_set_keyboard_mode(GTK_WINDOW(window), GTK_LAYER_SHELL_KEYBOARD_MODE_ON_DEMAND);

    GtkWidget *shell = make_shell(&app);
    gtk_container_add(GTK_CONTAINER(window), shell);
    update_clock(&app);
    update_calendar(&app);
    update_summary(&app);
    g_timeout_add_seconds(1, update_clock, &app);
    g_timeout_add_seconds(5, update_summary, &app);
    g_timeout_add(700, update_events, &app);

    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    gtk_widget_show_all(window);
    gtk_main();

    g_free(app.user);
    g_free(app.clipboard_text);
    curl_global_cleanup();
    return 0;
}
