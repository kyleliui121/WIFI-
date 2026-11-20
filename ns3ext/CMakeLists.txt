add_library(wifi-edca-crosscheck-dll SHARED wifi-edca-crosscheck.cc)
target_compile_definitions(wifi-edca-crosscheck-dll PRIVATE WIFI_CROSSCHECK_DLL)
target_link_libraries(wifi-edca-crosscheck-dll PRIVATE ${ns3-libs})
set_target_properties(wifi-edca-crosscheck-dll PROPERTIES OUTPUT_NAME wifi-edca-crosscheck)
