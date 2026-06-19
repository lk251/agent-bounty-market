{
  description = "Agent Bounty Market hackathon transaction core";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in {
      devShells.${system}.default = pkgs.mkShell {
        packages = [ pkgs.python312 pkgs.git ];
      };

      checks.${system}.unit = pkgs.runCommand "agent-bounty-market-tests" {
        nativeBuildInputs = [ pkgs.python312 pkgs.git ];
      } ''
        cp -R ${self} source
        chmod -R u+w source
        cd source
        python3 -m unittest discover -s tests
        python3 -m py_compile $(find agent_bounty verifiers tests -name '*.py' -print)
        touch $out
      '';
    };
}
