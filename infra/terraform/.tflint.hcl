# tflint: errores que validate no ve (SKUs, tipos de VM, nombres inválidos para Azure) y buenas prácticas.
#   docker run --rm -v ${PWD}:/data -w /data ghcr.io/terraform-linters/tflint:v0.66.0 --init
#   docker run --rm -v ${PWD}:/data -w /data ghcr.io/terraform-linters/tflint:v0.66.0 --recursive
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.33.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}
