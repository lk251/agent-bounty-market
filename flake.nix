{
  description = "Agent Bounty Market hackathon transaction core";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      stripePythonPackage = pkgs.python312Packages.stripe.overridePythonAttrs (_old: rec {
        version = "15.2.0";
        src = pkgs.fetchPypi {
          pname = "stripe";
          inherit version;
          hash = "sha256-95XYqP8nQz6asDCZr8D1xOmSqKb5K5+DncAEi7EvdvY=";
        };
      });
      pythonWithStripe = pkgs.python312.withPackages (_ps: [ stripePythonPackage ]);
    in {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          pythonWithStripe
          pkgs.git
          pkgs.nodejs_22
          pkgs.python311
          pkgs.stripe-cli
          pkgs.uv
        ];
      };

      checks.${system}.unit = pkgs.runCommand "agent-bounty-market-tests" {
        nativeBuildInputs = [ pythonWithStripe pkgs.git ];
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
