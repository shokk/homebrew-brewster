# Formula/brewster.rb
#
# Homebrew formula for Brewster.
#
# To update resource hashes after a new release, find each package on PyPI,
# grab the sdist URL and sha256 from the "Download files" tab, and update
# the resource blocks below.
#
# To test locally after tapping (brew tap shokk/brewster):
#   brew install --build-from-source shokk/brewster/brewster
#   brew test shokk/brewster/brewster
#   brew audit --strict --online shokk/brewster/brewster

class Brewster < Formula
  include Language::Python::Virtualenv

  desc "Track and sync Homebrew packages across machines via iCloud or any shared filesystem"
  homepage "https://github.com/shokk/homebrew-brewster"
  url "https://github.com/shokk/homebrew-brewster/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "a9a24cecf242ed277e35f1070c3d0dd0c3e110c41d572997a60396193c59d623"
  license "MIT"
  head "https://github.com/shokk/homebrew-brewster.git", branch: "main"

  # Python 3.11+ for stdlib tomllib.
  # brew's own Python — isolated from the user's python/pyenv/conda environment.
  depends_on "python@3.12"

  # ---------------------------------------------------------------------------
  # PyPI resources — update manually: get sdist URL + sha256 from PyPI JSON API
  #   python3 -c "import urllib.request,json; d=json.loads(urllib.request.urlopen('https://pypi.org/pypi/PACKAGE/VERSION/json').read()); [print(f['url'],f['digests']['sha256']) for f in d['urls'] if f['packagetype']=='sdist']"
  # ---------------------------------------------------------------------------

  resource "click" do
    url "https://files.pythonhosted.org/packages/96/d3/f04c7bfcf5c1862a2a5b845c6b2b360488cf47af55dfa79c98f6a6bf98b5/click-8.1.7.tar.gz"
    sha256 "ca9853ad459e787e2192211578cc907e7594e294c7ccc834310722b41b9ca6de"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/c0/8f/0722ca900cc807c13a6a0c696dacf35430f72e0ec571c4275d2371fca3e9/rich-15.0.0.tar.gz"
    sha256 "edd07a4824c6b40189fb7ac9bc4c52536e9780fbbfbddf6f1e2502c31b068c36"
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
    url "https://files.pythonhosted.org/packages/c3/b2/bc9c9196916376152d655522fdcebac55e66de6603a76a02bca1b6414f6c/pygments-2.20.0.tar.gz"
    sha256 "6757cd03768053ff99f3039c1a36d6c0aa0b263438fcab17520b30a303a82b5f"
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
