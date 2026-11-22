class Encodeassistant < Formula
  desc "Headless x264 tuning and matched B-frame review"
  homepage "https://github.com/maas3n/encodeassistant"
  version "0.1.0"
  license "MIT"

  on_macos do
    on_arm do
      url "https://github.com/maas3n/encodeassistant/releases/download/cli-v0.1.0/encodeassistant-macos-arm64.tar.gz"
      sha256 "9f5cc705c44ff74e155cf1bb07931f6c9f1dde25de7b60515b81fe2f352b182c"
    end

    on_intel do
      url "https://github.com/maas3n/encodeassistant/releases/download/cli-v0.1.0/encodeassistant-macos-x86_64.tar.gz"
      sha256 "c823d0e851cf36cb60b218e8277e467f4e596bdc1871824b6a814730f820e015"
    end
  end

  on_linux do
    on_arm do
      url "https://github.com/maas3n/encodeassistant/releases/download/cli-v0.1.0/encodeassistant-linux-arm64.tar.gz"
      sha256 "039027bf6fab57fc202f4d6a1796d134c39d77b66889504305fe500b5069744a"
    end

    on_intel do
      url "https://github.com/maas3n/encodeassistant/releases/download/cli-v0.1.0/encodeassistant-linux-x86_64.tar.gz"
      sha256 "5cbc24da5fda9f3c4f437f9f8e48829acf1401abaf23f4dac8e93eafb51dbc93"
    end
  end

  def install
    bin.install "encodeassistant"
  end

  test do
    assert_match "encodeassistant #{version}", shell_output("#{bin}/encodeassistant --version")
  end
end
