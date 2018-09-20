# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'infra/tilo',
    'recipe_engine/json',
    'recipe_engine/path',
]

PROPERTIES = {}

summary = {
  'tests': [
    {
      'name': '/system/test/wlan_client_unittest',
      'output_file': 'system/test/wlan_client_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/mediaplayer_tests',
      'output_file': 'system/test/mediaplayer_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/mediaplayer_core_tests',
      'output_file': 'system/test/mediaplayer_core_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/audio_core_tests',
      'output_file': 'system/test/audio_core_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/mediaplayer_demux_tests',
      'output_file': 'system/test/mediaplayer_demux_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_scanner_unittest',
      'output_file': 'system/test/wlan_scanner_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/audio_dfx_tests',
      'output_file': 'system/test/audio_dfx_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/libc-tests',
      'output_file': 'system/test/libc-tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/fostr_unittests',
      'output_file': 'system/test/fostr_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_timer_manager_unittest',
      'output_file': 'system/test/wlan_timer_manager_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_common_unittest',
      'output_file': 'system/test/wlan_common_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_mac_unittest',
      'output_file': 'system/test/wlan_mac_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_service_unittest',
      'output_file': 'system/test/wlan_service_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/svc_unittests',
      'output_file': 'system/test/svc_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/libc-large-tests',
      'output_file': 'system/test/libc-large-tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/crashpad_tests',
      'output_file': 'system/test/crashpad_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/simple_camera_unittests',
      'output_file': 'system/test/simple_camera_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/mediaplayer_util_tests',
      'output_file': 'system/test/mediaplayer_util_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/system/test/wlan_dispatcher_unittest',
      'output_file': 'system/test/wlan_dispatcher_unittest/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/all_services/0/test/run_all_services',
      'output_file': 'pkgfs/packages/all_services/0/test/run_all_services/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/amber_tests/0/test/amber_publish_test',
      'output_file': 'pkgfs/packages/amber_tests/0/test/amber_publish_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/amber_tests/0/test/amber_source_test',
      'output_file': 'pkgfs/packages/amber_tests/0/test/amber_source_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/amber_tests/0/test/amber_cmd_publish_test',
      'output_file': 'pkgfs/packages/amber_tests/0/test/amber_cmd_publish_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/amber_tests/0/test/amber_daemon_test',
      'output_file': 'pkgfs/packages/amber_tests/0/test/amber_daemon_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/amber_tests/0/test/amber_fidl_test',
      'output_file': 'pkgfs/packages/amber_tests/0/test/amber_fidl_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/appmgr_integration_tests/0/test/appmgr_hub_integration_tests',
      'output_file': 'pkgfs/packages/appmgr_integration_tests/0/test/appmgr_hub_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/appmgr_integration_tests/0/test/appmgr_realm_integration_tests',
      'output_file': 'pkgfs/packages/appmgr_integration_tests/0/test/appmgr_realm_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/appmgr_unittests/0/test/appmgr_unittests',
      'output_file': 'pkgfs/packages/appmgr_unittests/0/test/appmgr_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/ath10k_test/0/test/sparse_array_tests',
      'output_file': 'pkgfs/packages/ath10k_test/0/test/sparse_array_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/audio_mixer_tests/0/test/audio_mixer_tests',
      'output_file': 'pkgfs/packages/audio_mixer_tests/0/test/audio_mixer_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/auth_rust_tests/0/test/dev_auth_provider_iotid_rust_bin_test_rustc',
      'output_file': 'pkgfs/packages/auth_rust_tests/0/test/dev_auth_provider_iotid_rust_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/auth_rust_tests/0/test/dev_auth_provider_rust_bin_test_rustc',
      'output_file': 'pkgfs/packages/auth_rust_tests/0/test/dev_auth_provider_rust_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/auth_rust_tests/0/test/auth_cache_lib_test_rustc',
      'output_file': 'pkgfs/packages/auth_rust_tests/0/test/auth_cache_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/auth_rust_tests/0/test/auth_store_lib_test_rustc',
      'output_file': 'pkgfs/packages/auth_rust_tests/0/test/auth_store_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/bluetooth_tests/0/test/bt-host-unittests',
      'output_file': 'pkgfs/packages/bluetooth_tests/0/test/bt-host-unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/boringssl_tests/0/test/ssl_test',
      'output_file': 'pkgfs/packages/boringssl_tests/0/test/ssl_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/brcmfmac_test/0/test/workqueue_test',
      'output_file': 'pkgfs/packages/brcmfmac_test/0/test/workqueue_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/brcmfmac_test/0/test/netbuf_test',
      'output_file': 'pkgfs/packages/brcmfmac_test/0/test/netbuf_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/catapult_converter/0/test/catapult_converter_test',
      'output_file': 'pkgfs/packages/catapult_converter/0/test/catapult_converter_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/chrealm_integrationtests/0/test/chrealm_integration_tests',
      'output_file': 'pkgfs/packages/chrealm_integrationtests/0/test/chrealm_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/cmx_unittests/0/test/cmx_unittests',
      'output_file': 'pkgfs/packages/cmx_unittests/0/test/cmx_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/cobalt_tests/0/test/cobalt_app_unittests',
      'output_file': 'pkgfs/packages/cobalt_tests/0/test/cobalt_app_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/cobalt_tests/0/test/cobalt_testapp_no_network',
      'output_file': 'pkgfs/packages/cobalt_tests/0/test/cobalt_testapp_no_network/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/cobalt_tests/0/test/cobalt_encoder_unittests',
      'output_file': 'pkgfs/packages/cobalt_tests/0/test/cobalt_encoder_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/component_hello_world_tests/0/test/hello_world_test',
      'output_file': 'pkgfs/packages/component_hello_world_tests/0/test/hello_world_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/components_binary_test/0/test/components_binary_argv_test',
      'output_file': 'pkgfs/packages/components_binary_test/0/test/components_binary_argv_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/debug_agent_tests/0/test/debug_agent_tests',
      'output_file': 'pkgfs/packages/debug_agent_tests/0/test/debug_agent_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/debugger_utils_tests/0/test/debugger_utils_tests',
      'output_file': 'pkgfs/packages/debugger_utils_tests/0/test/debugger_utils_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/debugserver_tests/0/test/debugserver-unittests',
      'output_file': 'pkgfs/packages/debugserver_tests/0/test/debugserver-unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/device_settings_gotests/0/test/device_settings_integration_test',
      'output_file': 'pkgfs/packages/device_settings_gotests/0/test/device_settings_integration_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/dhcp_tests/0/test/dhcp_lib_test_rustc',
      'output_file': 'pkgfs/packages/dhcp_tests/0/test/dhcp_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/echo2_server_cpp_tests/0/test/echo2_server_cpp_unittests',
      'output_file': 'pkgfs/packages/echo2_server_cpp_tests/0/test/echo2_server_cpp_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/escher_tests/0/test/escher_unittests',
      'output_file': 'pkgfs/packages/escher_tests/0/test/escher_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/ethernet-tests/0/test/ethernet_lib_test_rustc',
      'output_file': 'pkgfs/packages/ethernet-tests/0/test/ethernet_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/fidl_compatibility_test/0/test/run_fidl_compatibility_test_garnet.sh',
      'output_file': 'pkgfs/packages/fidl_compatibility_test/0/test/run_fidl_compatibility_test_garnet.sh/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/fidl_tests/0/test/fidl_cpp_unittests',
      'output_file': 'pkgfs/packages/fidl_tests/0/test/fidl_cpp_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/font_provider_tests/0/test/font_provider_test',
      'output_file': 'pkgfs/packages/font_provider_tests/0/test/font_provider_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/fsl/0/test/fsl_unittests',
      'output_file': 'pkgfs/packages/fsl/0/test/fsl_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/fxl_unittests/0/test/fxl_unittests',
      'output_file': 'pkgfs/packages/fxl_unittests/0/test/fxl_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/garnet-rust-examples/0/test/testing_integration_test_two',
      'output_file': 'pkgfs/packages/garnet-rust-examples/0/test/testing_integration_test_two/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/garnet-rust-examples/0/test/testing_lib_test_rustc',
      'output_file': 'pkgfs/packages/garnet-rust-examples/0/test/testing_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/garnet-rust-examples/0/test/testing_integration_test',
      'output_file': 'pkgfs/packages/garnet-rust-examples/0/test/testing_integration_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/garnet_lib_tests/0/test/garnet_lib_unittests',
      'output_file': 'pkgfs/packages/garnet_lib_tests/0/test/garnet_lib_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_benchmarking_tests/0/test/go_benchmarking_test',
      'output_file': 'pkgfs/packages/go_benchmarking_tests/0/test/go_benchmarking_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_far_tests/0/test/go_far_test',
      'output_file': 'pkgfs/packages/go_far_tests/0/test/go_far_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_merkle_tests/0/test/go_merkle_test',
      'output_file': 'pkgfs/packages/go_merkle_tests/0/test/go_merkle_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_stdlib_tests/0/test/go_net_test',
      'output_file': 'pkgfs/packages/go_stdlib_tests/0/test/go_net_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_stdlib_tests/0/test/go_os_test',
      'output_file': 'pkgfs/packages/go_stdlib_tests/0/test/go_os_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_stdlib_tests/0/test/go_zxwait_test',
      'output_file': 'pkgfs/packages/go_stdlib_tests/0/test/go_zxwait_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/go_stdlib_tests/0/test/go_dispatch_test',
      'output_file': 'pkgfs/packages/go_stdlib_tests/0/test/go_dispatch_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/guest_integration_tests/0/test/guest_integration_tests',
      'output_file': 'pkgfs/packages/guest_integration_tests/0/test/guest_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/guestmgr_tests/0/test/guestmgr_unittests',
      'output_file': 'pkgfs/packages/guestmgr_tests/0/test/guestmgr_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/has_persistent_storage/0/test/run_has_persistent_storage',
      'output_file': 'pkgfs/packages/has_persistent_storage/0/test/run_has_persistent_storage/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/has_shell/0/test/run_has_shell',
      'output_file': 'pkgfs/packages/has_shell/0/test/run_has_shell/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/has_system_temp/0/test/run_has_system_temp',
      'output_file': 'pkgfs/packages/has_system_temp/0/test/run_has_system_temp/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/http_service_tests/0/test/http_service_tests',
      'output_file': 'pkgfs/packages/http_service_tests/0/test/http_service_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/inferior_control_tests/0/test/inferior_control_tests',
      'output_file': 'pkgfs/packages/inferior_control_tests/0/test/inferior_control_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/inspect_integration_tests/0/test/inspect_integration_tests',
      'output_file': 'pkgfs/packages/inspect_integration_tests/0/test/inspect_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/iquery_golden_test/0/test/iquery_golden_test',
      'output_file': 'pkgfs/packages/iquery_golden_test/0/test/iquery_golden_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/json_unittests/0/test/json_unittests',
      'output_file': 'pkgfs/packages/json_unittests/0/test/json_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/log_listener_tests/0/test/log_listener_bin_test_rustc',
      'output_file': 'pkgfs/packages/log_listener_tests/0/test/log_listener_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/logger_integration_tests/0/test/logger_integration_go_tests',
      'output_file': 'pkgfs/packages/logger_integration_tests/0/test/logger_integration_go_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/logger_integration_tests/0/test/logger_integration_bin_test_rustc',
      'output_file': 'pkgfs/packages/logger_integration_tests/0/test/logger_integration_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/logger_integration_tests/0/test/logger_integration_cpp_tests',
      'output_file': 'pkgfs/packages/logger_integration_tests/0/test/logger_integration_cpp_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/logger_tests/0/test/logger_bin_test_rustc',
      'output_file': 'pkgfs/packages/logger_tests/0/test/logger_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/machina_tests/0/test/machina_unittests',
      'output_file': 'pkgfs/packages/machina_tests/0/test/machina_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool_free_list_only',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool_free_list_only/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/msd_intel_gen_nonhardware_tests',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/msd_intel_gen_nonhardware_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/block_pool_no_free',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/block_pool_no_free/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/mesa_unit_tests',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/mesa_unit_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool_no_free',
      'output_file': 'pkgfs/packages/magma_intel_gen_nonhardware_tests/0/test/state_pool_no_free/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/magma_nonhardware_tests/0/test/magma_unit_tests',
      'output_file': 'pkgfs/packages/magma_nonhardware_tests/0/test/magma_unit_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/media_examples_tests/0/test/use_aac_decoder_test',
      'output_file': 'pkgfs/packages/media_examples_tests/0/test/use_aac_decoder_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/media_lib_timeline_tests/0/test/media_lib_timeline_tests',
      'output_file': 'pkgfs/packages/media_lib_timeline_tests/0/test/media_lib_timeline_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/media_lib_transport_tests/0/test/media_lib_transport_tests',
      'output_file': 'pkgfs/packages/media_lib_transport_tests/0/test/media_lib_transport_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/mime_sniffer_unittests/0/test/mime_sniffer_unittests',
      'output_file': 'pkgfs/packages/mime_sniffer_unittests/0/test/mime_sniffer_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/multiple_components/0/test/run_multiple_components',
      'output_file': 'pkgfs/packages/multiple_components/0/test/run_multiple_components/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_netiface_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_netiface_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_netstat_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_netstat_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_fidlconv_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_fidlconv_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_link_eth_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_link_eth_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_ifconfig_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_ifconfig_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_connectivity_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_connectivity_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_gotests/0/test/netstack_filter_test',
      'output_file': 'pkgfs/packages/netstack_gotests/0/test/netstack_filter_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_integration/0/test/netstack_launch_test',
      'output_file': 'pkgfs/packages/netstack_integration/0/test/netstack_launch_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_tests/0/test/netstack_gonet_test',
      'output_file': 'pkgfs/packages/netstack_tests/0/test/netstack_gonet_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_tests/0/test/netstack_loopback_test',
      'output_file': 'pkgfs/packages/netstack_tests/0/test/netstack_loopback_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/netstack_tests/0/test/netstack_launch_test',
      'output_file': 'pkgfs/packages/netstack_tests/0/test/netstack_launch_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/network_time_tests/0/test/network_time_tests',
      'output_file': 'pkgfs/packages/network_time_tests/0/test/network_time_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/no_persistent_storage/0/test/run_no_persistent_storage',
      'output_file': 'pkgfs/packages/no_persistent_storage/0/test/run_no_persistent_storage/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/no_services/0/test/run_no_services',
      'output_file': 'pkgfs/packages/no_services/0/test/run_no_services/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/no_shell/0/test/run_no_shell',
      'output_file': 'pkgfs/packages/no_shell/0/test/run_no_shell/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/no_system_temp/0/test/run_no_system_temp',
      'output_file': 'pkgfs/packages/no_system_temp/0/test/run_no_system_temp/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/overnet_tests/0/test/overnet_unittests',
      'output_file': 'pkgfs/packages/overnet_tests/0/test/overnet_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/pkg_url_unittests/0/test/pkg_url_unittests',
      'output_file': 'pkgfs/packages/pkg_url_unittests/0/test/pkg_url_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/pmd_tests/0/test/pmd_index_test',
      'output_file': 'pkgfs/packages/pmd_tests/0/test/pmd_index_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/pmd_tests/0/test/pmd_pkgfs_test',
      'output_file': 'pkgfs/packages/pmd_tests/0/test/pmd_pkgfs_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/power_manager_gotests/0/test/power_manager_test',
      'output_file': 'pkgfs/packages/power_manager_gotests/0/test/power_manager_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/power_manager_tests/0/test/power_manager_bin_test_rustc',
      'output_file': 'pkgfs/packages/power_manager_tests/0/test/power_manager_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/process_unittests/0/test/process_unittests',
      'output_file': 'pkgfs/packages/process_unittests/0/test/process_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/recovery_netstack_tests/0/test/recovery_netstack_bin_test_rustc',
      'output_file': 'pkgfs/packages/recovery_netstack_tests/0/test/recovery_netstack_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/recovery_netstack_tests/0/test/netstack_core_lib_test_rustc',
      'output_file': 'pkgfs/packages/recovery_netstack_tests/0/test/netstack_core_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/run_test_component_test/0/test/run_test_component_test',
      'output_file': 'pkgfs/packages/run_test_component_test/0/test/run_test_component_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/run_test_component_unittests/0/test/run_test_component_unittests',
      'output_file': 'pkgfs/packages/run_test_component_unittests/0/test/run_test_component_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/run_tests/0/test/run_return_value_shell_test',
      'output_file': 'pkgfs/packages/run_tests/0/test/run_return_value_shell_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/run_tests/0/test/run_tests',
      'output_file': 'pkgfs/packages/run_tests/0/test/run_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/run_tests/0/test/run_return_value_test',
      'output_file': 'pkgfs/packages/run_tests/0/test/run_return_value_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fidl_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fidl_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fuchsia_syslog_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fuchsia_syslog_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fuchsia_trace_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fuchsia_trace_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/mapped_vmo_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/mapped_vmo_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/mundane_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/mundane_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/shared_buffer_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/shared_buffer_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fuchsia_zircon_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fuchsia_zircon_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fuchsia_async_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fuchsia_async_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/zerocopy_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/zerocopy_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fdio_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fdio_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/rust-crates-tests/0/test/fuchsia_merkle_lib_test_rustc',
      'output_file': 'pkgfs/packages/rust-crates-tests/0/test/fuchsia_merkle_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/gfx_apptests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/gfx_apptests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/presentation_mode_unittests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/presentation_mode_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/input_apptests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/input_apptests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/scenic_unittests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/scenic_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/geometry_util_unittests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/geometry_util_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/gfx_unittests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/gfx_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/scenic_tests/0/test/view_manager_apptests',
      'output_file': 'pkgfs/packages/scenic_tests/0/test/view_manager_apptests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/some_services/0/test/run_some_services',
      'output_file': 'pkgfs/packages/some_services/0/test/run_some_services/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/stash_tests/0/test/stash_bin_test_rustc',
      'output_file': 'pkgfs/packages/stash_tests/0/test/stash_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/syslog_cpp_tests/0/test/syslog_cpp_unittests',
      'output_file': 'pkgfs/packages/syslog_cpp_tests/0/test/syslog_cpp_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/syslog_gotests/0/test/syslog_go_tests',
      'output_file': 'pkgfs/packages/syslog_gotests/0/test/syslog_go_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/sysmgr_integration_tests/0/test/service_startup_test',
      'output_file': 'pkgfs/packages/sysmgr_integration_tests/0/test/service_startup_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/sysmgr_tests/0/test/ls_svc_test',
      'output_file': 'pkgfs/packages/sysmgr_tests/0/test/ls_svc_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/sysmgr_tests/0/test/config_test',
      'output_file': 'pkgfs/packages/sysmgr_tests/0/test/config_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/test_with_context_example_test/0/test/test_with_context_example_test',
      'output_file': 'pkgfs/packages/test_with_context_example_test/0/test/test_with_context_example_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/test_with_environment_example_test/0/test/test_with_environment_example_test',
      'output_file': 'pkgfs/packages/test_with_environment_example_test/0/test/test_with_environment_example_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/tiles_tests/0/test/tiles_unittests',
      'output_file': 'pkgfs/packages/tiles_tests/0/test/tiles_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/timezone_tests/0/test/timezone_unittests',
      'output_file': 'pkgfs/packages/timezone_tests/0/test/timezone_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/token_manager_tests/0/test/dev_token_mgr_e2e_test',
      'output_file': 'pkgfs/packages/token_manager_tests/0/test/dev_token_mgr_e2e_test/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/token_manager_tests/0/test/token_manager_unittests',
      'output_file': 'pkgfs/packages/token_manager_tests/0/test/token_manager_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/trace_tests/0/test/trace_integration_tests',
      'output_file': 'pkgfs/packages/trace_tests/0/test/trace_integration_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/trace_tests/0/test/trace_tests',
      'output_file': 'pkgfs/packages/trace_tests/0/test/trace_tests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/url_tests/0/test/url_apptests',
      'output_file': 'pkgfs/packages/url_tests/0/test/url_apptests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/vmm_tests/0/test/vmm_unittests',
      'output_file': 'pkgfs/packages/vmm_tests/0/test/vmm_unittests/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wayland_tests/0/test/fuchsia_wayland_core_lib_test_rustc',
      'output_file': 'pkgfs/packages/wayland_tests/0/test/fuchsia_wayland_core_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wayland_tests/0/test/wayland_scanner_back_end_test_lib_test_rustc',
      'output_file': 'pkgfs/packages/wayland_tests/0/test/wayland_scanner_back_end_test_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wayland_tests/0/test/wayland_scanner_front_end_test_lib_test_rustc',
      'output_file': 'pkgfs/packages/wayland_tests/0/test/wayland_scanner_front_end_test_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'FAIL'
    },
    {
      'name': '/pkgfs/packages/wlan-hw-sim-tests/0/test/wlan-hw-sim_bin_test_rustc',
      'output_file': 'pkgfs/packages/wlan-hw-sim-tests/0/test/wlan-hw-sim_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wlan-rsn-tests/0/test/wlan_rsn_lib_test_rustc',
      'output_file': 'pkgfs/packages/wlan-rsn-tests/0/test/wlan_rsn_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wlan-sme-tests/0/test/wlan_sme_lib_test_rustc',
      'output_file': 'pkgfs/packages/wlan-sme-tests/0/test/wlan_sme_lib_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wlancfg-tests/0/test/wlancfg_bin_test_rustc',
      'output_file': 'pkgfs/packages/wlancfg-tests/0/test/wlancfg_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wlanstack2-tests/0/test/wlanstack2_bin_test_rustc',
      'output_file': 'pkgfs/packages/wlanstack2-tests/0/test/wlanstack2_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/wlantool2-tests/0/test/wlantool2_bin_test_rustc',
      'output_file': 'pkgfs/packages/wlantool2-tests/0/test/wlantool2_bin_test_rustc/stdout-and-stderr.txt',
      'result': 'PASS'
    },
    {
      'name': '/pkgfs/packages/zircon_benchmarks/0/test/zircon_benchmarks',
      'output_file': 'pkgfs/packages/zircon_benchmarks/0/test/zircon_benchmarks/stdout-and-stderr.txt',
      'result': 'PASS'
    }
  ],
  'outputs': {
    'syslog_file': 'syslog.txt'
  }
}

def RunSteps(api):
  # Initialize the Tilo database.
  api.tilo.set_database_path(api.path['start_dir'].join('tilo.database'))
 
  # Create the invocation
  api.tilo.invocation_start()

  # Log targets and tests for every entry in the summary file.
  api.tilo.process_summary(summary=api.json.input(summary))

  # Determine whether any tests failed, and record the invocatin as a failure if
  # so.
  invocation_result = api.tilo.InvocationPassed
  for entry in summary["tests"]:
    if entry["result"] != "PASS":
      invocation_result = api.tilo.InvocationFailed
      break

  # Close the invocation for editing.  
  api.tilo.invocation_end(result=invocation_result)

def GenTests(api):
  pass
