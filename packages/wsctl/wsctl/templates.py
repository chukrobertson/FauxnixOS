from __future__ import annotations


TEMPLATE_KEYWORDS: dict[str, list[str]] = {
    "ml-python": [
        "ml", "machine learning", "deep learning", "ai", "artificial intelligence",
        "pytorch", "tensorflow", "jupyter", "python data", "training", "neural",
        "transformer", "llm", "model", "gpu", "cuda", "data science",
    ],
    "coding": [
        "code", "coding", "programming", "develop", "dev", "software",
        "compile", "build", "debug", "ide", "editor", "terminal",
        "rust", "go", "golang", "javascript", "typescript", "node",
        "java", "kotlin", "swift", "zig", "haskell", "cpp", "c++",
        "c language", "python", "script", "shell", "bash",
    ],
    "rust-dev": [
        "rust", "cargo", "rustc", "rustlang",
    ],
    "web-dev": [
        "web", "website", "frontend", "backend", "react", "vue",
        "angular", "html", "css", "nodejs", "npm", "pnpm",
        "api", "rest", "graphql", "fullstack",
    ],
    "writing": [
        "write", "writing", "blog", "article", "essay", "story",
        "novel", "book", "chapter", "manuscript", "markdown",
    ],
    "documents": [
        "document", "documents", "pdf", "word", "office", "libreoffice",
        "publish", "publishing", "latex", "pandoc", "ebook", "epub",
        "print", "paper", "report", "proposal", "presentation",
    ],
    "research": [
        "research", "reference", "note", "notes", "study", "learn",
        "browser", "firefox", "chromium", "wiki", "wikipedia",
        "paper", "papers", "arxiv", "citation", "zotero",
        "browse", "reading", "read",
    ],
    "audio": [
        "audio", "music", "sound", "podcast", "recording",
        "daw", "mix", "master", "audacity", "midi",
        "synthesizer", "sample", "beat", "instrument",
    ],
    "image-video": [
        "image", "images", "photo", "photos", "picture", "pictures",
        "video", "videos", "edit", "editing", "gimp", "photoshop",
        "blender", "kdenlive", "premiere", "render", "animation",
        "design", "graphic", "visual", "draw", "paint",
        "screenshot", "screen recording",
    ],
    "gaming": [
        "game", "games", "gaming", "steam", "play", "proton",
        "wine", "lutris", "fps", "rpg", "mmo", "minecraft",
    ],
}


def match_template(query: str) -> str:
    query_lower = query.lower()
    scores: dict[str, int] = {}

    for template, keywords in TEMPLATE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in query_lower:
                score += len(kw)
        if score > 0:
            scores[template] = score

    if not scores:
        return "coding"

    return max(scores, key=lambda k: scores[k])


def template_description(template_name: str) -> str:
    descriptions: dict[str, str] = {
        "ml-python": "Python ML/Data Science — PyTorch, Jupyter, NumPy, Pandas",
        "coding": "General coding — Python, Rust, Go, Node.js, C, git, neovim, tmux",
        "rust-dev": "Rust development — cargo, rustc, rust-analyzer, clippy",
        "web-dev": "Web development — Node.js, TypeScript, VS Code",
        "writing": "Writing — Pandoc, Zathura, LaTeX, spellcheck",
        "documents": "Documents — LibreOffice, Pandoc, LaTeX, Calibre, PDF tools",
        "research": "Research — Firefox, Obsidian, Zotero, clipboard, notes",
        "audio": "Audio — Ardour, Audacity, LMMS, FFmpeg, SoX",
        "image-video": "Image & Video — GIMP, Inkscape, Blender, Kdenlive, OBS",
        "gaming": "Gaming — Steam, Lutris, Wine, GameMode, MangoHud",
    }
    return descriptions.get(template_name, template_name)
