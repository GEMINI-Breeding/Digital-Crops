# Command Line Argument Parsing 개선 가이드

## 질문: if-else vs switch-case, 어떤 것이 더 나을까?

### 결론: **if-else가 더 적합합니다** (하지만 리팩토링 추천)

## 왜 switch-case가 부적합한가?

### 1. **C++ switch는 문자열을 지원하지 않음**
```cpp
// ❌ 불가능 - C++ switch는 std::string을 직접 사용할 수 없음
switch(arg) {
    case "-r":  // 컴파일 에러!
        break;
}
```

### 2. **복잡한 조건 처리 어려움**
- 각 옵션마다 `i + 1 < argc` 같은 추가 조건이 필요
- 다음 인자를 읽는 `argv[++i]` 로직 필요
- switch-case는 이런 복잡한 로직에 부적합

### 3. **해시맵 방식도 복잡함**
```cpp
// 가능하지만 코드가 더 복잡해짐
std::unordered_map<std::string, std::function<void()>> handlers;
```

## ✅ 추천하는 개선 방법

### 방법 1: 구조체 + 전용 파싱 함수 (현재 적용됨)

**장점:**
- ✅ 코드 분리로 main() 함수가 깔끔해짐
- ✅ 옵션을 구조체로 관리하여 타입 안전성 보장
- ✅ 재사용성 향상
- ✅ 테스트하기 쉬움
- ✅ --help 옵션 추가 용이

**구현된 코드:**

#### main.h - 옵션 구조체 정의
```cpp
struct CommandLineOptions {
    bool rotation_view = false;
    bool grow = false;
    bool debug = false;
    bool save_xml = false;
    bool stats_only = false;
    float height = 0.0f;
    int days = 0;
    unsigned int seed = 0;
    std::string tile_file;
    std::string save_dir;
    std::string plant_model_file;
    std::string output_name;
};

CommandLineOptions parseCommandLineArgs(int argc, char* argv[]);
```

#### utils.cpp - 파싱 함수 구현
```cpp
CommandLineOptions parseCommandLineArgs(int argc, char* argv[]) {
    CommandLineOptions options;
    
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        
        // Boolean flags
        if (arg == "-r") {
            options.rotation_view = true;
        } else if (arg == "-g") {
            options.grow = true;
        }
        // ... 기타 옵션들
        else if (arg == "--help") {
            // 도움말 출력
            std::exit(0);
        }
    }
    
    return options;
}
```

#### main.cpp - 사용
```cpp
int main(int argc, char* argv[]) {
    // 단 한 줄로 모든 argument 파싱!
    CommandLineOptions options = parseCommandLineArgs(argc, argv);
    
    // 이제 options.rotation_view 같은 방식으로 접근
    if (options.debug) {
        std::cout << "Debug mode enabled" << std::endl;
    }
}
```

### 방법 2: 외부 라이브러리 사용 (선택사항)

더 강력한 기능이 필요하다면:

#### CLI11 (추천)
```cpp
#include "CLI/CLI.hpp"

int main(int argc, char* argv[]) {
    CLI::App app{"My Application"};
    
    bool rotation_view = false;
    int days = 0;
    std::string output_name;
    
    app.add_flag("-r,--rotation", rotation_view, "Enable rotation view");
    app.add_option("-days", days, "Number of days");
    app.add_option("-name", output_name, "Output name");
    
    CLI11_PARSE(app, argc, argv);
}
```

#### Boost.Program_options
```cpp
#include <boost/program_options.hpp>

namespace po = boost::program_options;

int main(int argc, char* argv[]) {
    po::options_description desc("Allowed options");
    desc.add_options()
        ("help", "produce help message")
        ("rotation,r", "enable rotation view")
        ("days", po::value<int>(), "number of days");
    
    po::variables_map vm;
    po::store(po::parse_command_line(argc, argv, desc), vm);
}
```

## 비교 표

| 방식 | 가독성 | 유지보수 | 확장성 | 복잡도 | 추천도 |
|------|--------|----------|--------|--------|--------|
| **긴 if-else** | ⭐⭐ | ⭐⭐ | ⭐⭐ | 높음 | ❌ |
| **switch-case** | ⭐ | ⭐ | ⭐ | 매우높음 | ❌❌ |
| **구조체 + 함수** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 낮음 | ✅✅✅ |
| **CLI11** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 매우낮음 | ⭐ |
| **Boost** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 낮음 | ⭐ |

## 현재 프로젝트에 적용된 개선사항

### Before (원래 코드)
```cpp
int main(int argc, char* argv[]) {
    // 34줄의 if-else 체인...
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-r") {
            rotation_view = true;
        } else if (arg == "-g") {
            grow = true;
        } // ... 30줄 더...
    }
    
    // 실제 로직 시작
}
```

### After (개선된 코드)
```cpp
int main(int argc, char* argv[]) {
    // 단 한 줄로 파싱 완료!
    CommandLineOptions options = parseCommandLineArgs(argc, argv);
    
    // 실제 로직 시작 (main이 훨씬 깔끔함)
}
```

## 추가 개선 사항

1. **--help 옵션 추가** ✅
   - `./main --help` 실행 시 사용법 출력

2. **타입 안전성** ✅
   - 구조체를 사용하여 컴파일 타임에 타입 체크

3. **기본값 설정** ✅
   - 구조체 멤버 초기화로 기본값 명확히 정의

4. **에러 처리 개선 가능**
   - 잘못된 옵션에 대한 명확한 에러 메시지

## 결론

**if-else vs switch-case?**
→ **if-else가 낫지만, 구조체 + 전용 함수로 리팩토링하는 것이 최선!**

현재 프로젝트는 이미 구조체 + 전용 함수 방식으로 개선되었습니다. 🎉
