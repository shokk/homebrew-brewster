# Formula/brewster.rb
#
# Homebrew formula for Brewster.
#
# To update resource hashes after a new release:
#   brew update-python-resources Formula/brewster.rb
#
# To test locally before pushing:
#   brew install --build-from-source Formula/brewster.rb
#   brew test brewster
#   brew audit --strict Formula/brewster.rb

class Brewster < Formula
  include Language::Python::Virtualenv

  desc "Track and sync Homebrew packages across machines via iCloud or any shared filesystem"
  homepage "https://github.com/shokk/homebrew-brewster"
  url "https://github.com/shokk/homebrew-brewster/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "86a6487489d1161178590431644cc84a93989e10b0933cfd65bff24418431001"
  license "MIT"
  head "https://github.com/shokk/homebrew-brewster.git", branch: "main"

  # Python 3.11+ for stdlib tomllib.
  # brew's own Python — isolated from the user's python/pyenv/conda environment.
  depends_on "python@3.12"

  # ---------------------------------------------------------------------------
  # PyPI resources
  # Run `brew update-python-resources Formula/brewster.rb` to regenerate these.
  # ---------------------------------------------------------------------------

  resource "click" do
    url "https://files.pythonhosted.org/packages/96/d3/f04c7bfcf5c1862a2a5b845c6b2b360488cf47af55dfa79c98f6a6bf98b5/click-8.1.7.tar.gz"
    sha256 "ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/a7/ec/4a7d80728bd429f7c0d4d51245287158a1516315cadbb146012439a8b01c/rich-13.7.1.tar.gz"
    sha256 "9be308cb1fe2f1f57d67ce99e95af38a1e2bc71ad9813b0e247cf7ffbcc3a432"
  end

  # rich dependencies
  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/38/71/3b932df36c1a044d397a1f92d1cf91ee0a503d91e470cbd670aa66b07ed0/markdown-it-py-3.0.0.tar.gz"
    sha256 "e3f60a94fa066dc52ec76661e37c851cb232d92f9886b15cb560aaada2df8feb"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/8e/62/8336eff65bcbc8e4cb5d05b55faf041285951b6e80f33e2bff2024788f31/pygments-2.17.2.tar.gz"
    sha256 "da46cec9fd2de5be3a8a784f434e4c4ab670b4ff54d605c4c2717e9d49c4c367"
  end

  def install
    virtualenv_install_with_resources

    # Shell completions — click can generate these automatically.
    # Generating them here at install time means they don't require
    # the user to have the package installed separately.
    generate_completions_from_executable(bin/"brewster", shells: [:bash, :zsh, :fish],
                                         shell_parameter_format: :click)
  end

  # Installed a launchd plist so `brewster sync` runs on login?
  # Use the service block (Homebrew Services integration):
  service do
    run [opt_bin/"brewster", "sync", "--quiet"]
    keep_alive false
    run_at_load true
    log_path var/"log/brewster.log"
    error_log_path var/"log/brewster.log"
  end

  test do
    # Basic smoke test: --version must exit 0 and print the version string.
    assert_match "#{version}", shell_output("#{bin}/brewster --version")

    # Verify the DB can be created and migrated in a temp dir.
    ENV["BREWSTER_DB_PATH"] = "#{testpath}/test.db"
    system bin/"brewster", "status"
    assert_predicate testpath/"test.db", :exist?
  end
end
