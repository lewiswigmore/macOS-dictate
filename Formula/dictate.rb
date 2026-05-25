class Dictate < Formula
  include Language::Python::Virtualenv

  desc "Privacy-first macOS voice dictation"
  homepage "https://github.com/lewiswigmore/dictate"
  url "https://github.com/lewiswigmore/dictate/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "MIT"
  head "https://github.com/lewiswigmore/dictate.git", branch: "main"

  depends_on "python@3.12"
  depends_on macos: :ventura
  depends_on :macos

  # Heavy native deps (faster-whisper, onnxruntime, pyobjc) are resolved by pip.
  def install
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install_and_link buildpath
  end

  def caveats
    <<~EOS
      dictate requires the following macOS permissions to function:
        - Accessibility (for synthetic Cmd+V insertion + hotkey event tap)
        - Microphone
        - Input Monitoring

      Grant them via System Settings -> Privacy & Security.

      For optional local LLM cleanup, install Ollama:
        brew install --cask ollama
        ollama pull qwen2.5:3b-instruct

      For optional cloud cleanup via OpenRouter, set:
        export OPENROUTER_API_KEY=sk-or-...

      Start dictate:
        dictate

      Open WebUI for history review:
        dictate-web
    EOS
  end

  test do
    system bin/"dictate", "--version"
  end
end
