"""Unit test of the NVIDIA kCFI type check (python3 -B -m unittest discover -s forge/specs/azoth/tests -v)."""

import pathlib
import sys
import tempfile
import unittest

AZOTH = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AZOTH / "nvidia"))
import kcfi_check  # noqa: E402

HEADER = "const BINDATA_ARCHIVE * ksec2GetX_AD10X(struct OBJGPU *pGpu, struct KernelSec2 *pKernelSec2);\n"
TABLE = """static NV_STATUS subCtrlA__EXPORT(void *pSubdevice, void *pParams) {{ return 0; }}
static NV_STATUS subCtrlB__EXPORT(void *pSubdevice) {{ return 0; }}
    {{
        /*pFunc=*/      (void (*)(void)) &subCtrlA__EXPORT,
        /*paramSize=*/  {a},
    }},
    {{
        /*pFunc=*/      (void (*)(void)) &subCtrlB__EXPORT,
        /*paramSize=*/  {b},
    }},
"""
EXPORT_CAST = (
    "src/nvidia/generated/g_subdevice_nvoc.c:10:25: warning: cast from 'NV_STATUS (*)(void *, void *)' "
    "(aka 'unsigned int (*)(void *, void *)') to 'void (*)(void)' converts to incompatible function type "
    "[-Wcast-function-type-strict]\n"
)


class Check(unittest.TestCase):
    def tree(self, getter_params, param_sizes):
        root = pathlib.Path(tempfile.mkdtemp())
        generated = root / "src/nvidia/generated"
        generated.mkdir(parents=True)
        (generated / "g_kernel_sec2_nvoc.h").write_text(HEADER)
        (generated / "g_bindata_ksec2GetX_AD10X.c").write_text(
            f"const BINDATA_ARCHIVE *ksec2GetX_AD10X({getter_params})\n{{\n    return NULL;\n}}\n"
        )
        (generated / "g_subdevice_nvoc.c").write_text(
            TABLE.format(a=param_sizes[0], b=param_sizes[1])
        )
        return generated

    def test_consistent_tree_and_log_pass(self):
        generated = self.tree(
            "struct OBJGPU *pGpu, struct KernelSec2 *pKernelSec2",
            ("sizeof(P)", "0 /* Singleton parameter list */"),
        )
        self.assertEqual(
            kcfi_check.bindata(generated)
            + kcfi_check.exports(generated)
            + kcfi_check.casts(EXPORT_CAST),
            [],
        )

    def test_bindata_getter_with_the_wrong_type_fails(self):
        generated = self.tree("struct KernelSec2 *pKernelSec2", ("sizeof(P)", "0"))
        self.assertEqual(len(kcfi_check.bindata(generated)), 1)
        self.assertIn("ksec2GetX_AD10X", kcfi_check.bindata(generated)[0])

    def test_export_arity_against_param_size_fails(self):
        generated = self.tree(
            "struct OBJGPU *pGpu, struct KernelSec2 *pKernelSec2", ("0", "sizeof(P)")
        )
        self.assertEqual(len(kcfi_check.exports(generated)), 2)

    def test_cast_outside_the_exceptions_fails(self):
        dtor = (
            "src/nvidia/generated/g_rpc_iom.c:68:5: warning: cast from 'void (*)(POBJRPC)' to 'NVOC_DYNAMIC_DTOR' "
            "(aka 'void (*)(struct Dynamic *)') converts to incompatible function type [-Wcast-function-type-strict]\n"
        )
        self.assertEqual(
            kcfi_check.casts(EXPORT_CAST + dtor),
            ["casts: generated/g_rpc_iom.c: void (*)(POBJRPC) -> NVOC_DYNAMIC_DTOR"],
        )

    def test_enum_against_integer_slot_fails(self):
        enum = (
            "kernel-open/nvidia-drm/nvidia-drm-connector.c:636:21: warning: incompatible function pointer types "
            "initializing 'enum drm_mode_status (*)(struct drm_connector *)' with an expression of type "
            "'int (struct drm_connector *)' [-Wincompatible-function-pointer-types-strict]\n"
        )
        found = kcfi_check.casts(EXPORT_CAST + enum)
        self.assertEqual(len(found), 1)
        self.assertIn("nvidia-drm-connector.c", found[0])

    def test_a_log_without_the_warning_fails(self):
        self.assertEqual(len(kcfi_check.casts("CC foo.c\n")), 1)


if __name__ == "__main__":
    unittest.main()
